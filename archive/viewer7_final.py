import sys
import json
import os
import re
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QFileSystemModel, QTreeView, QListWidget,
    QPushButton, QVBoxLayout, QHBoxLayout, QWidget, QFileDialog, QListWidgetItem,
    QScrollArea, QLabel, QMessageBox, QMenu, QToolTip, QLineEdit, QSizePolicy,
    QSlider, QAbstractItemView, QComboBox, QStyle, QStackedLayout, QGroupBox,
    QSplitter
)
from PySide6.QtGui import (
    QPixmap, QPalette, QColor, QAction, QFont, QIcon, QKeySequence
)
from PySide6.QtCore import (
    Qt, QPoint, QDir, QModelIndex, QRegularExpression,
    QSortFilterProxyModel, Signal, QEvent, QTimer
)


class CustomSortFilterProxyModel(QSortFilterProxyModel):
    itemRenamed = Signal(str)

    def __init__(self, extensions, favorites, parent=None):
        """
        초기화 함수입니다.
        favorites: 즐겨찾기 파일 경로가 담긴 set
        """
        super().__init__(parent)
        self.extensions = extensions
        self.favorites = favorites
        self.favorites_only_mode = False
        self._filter_regex = QRegularExpression("")
        self.setRecursiveFilteringEnabled(False)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        """
        파일 확장자를 표시하고, 즐겨찾기 항목에 별표(⭐)를 추가하며, 편집 시에는 확장자를 제외합니다.
        """
        source_index = self.mapToSource(index)
        file_path = self.sourceModel().filePath(source_index)
        file_name = self.sourceModel().fileName(source_index)

        if role == Qt.DisplayRole:
            # For display, show full name with extension
            display_name = file_name
            if os.path.isfile(file_path):
                if file_path in self.favorites:
                    return f"⭐ {display_name}"
                else:
                    return display_name
            return display_name  # For directories

        if role == Qt.EditRole:
            # For editing, show name without extension for files
            if os.path.isfile(file_path):
                return os.path.splitext(file_name)[0]
            else:
                return file_name # For directories

        return super().data(index, role)

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        """
        파일 및 폴더를 필터링하는 규칙을 정의합니다.
        즐겨찾기 모드일 때와 일반 모드일 때를 구분하여 필터링합니다.
        """
        source_model = self.sourceModel()
        index = source_model.index(source_row, 0, source_parent)
        file_path = source_model.filePath(index)
        is_dir = source_model.isDir(index)

        # 즐겨찾기 보기 모드
        if self.favorites_only_mode:
            if is_dir:
                # 폴더는 항상 표시하여 하위의 즐겨찾기 항목을 찾을 수 있도록 함
                return True
            else:
                # 파일인 경우 즐겨찾기 목록에 있는지 확인
                return file_path in self.favorites

        # 일반 검색 모드
        file_name = source_model.fileName(index)
        if is_dir:
            return True
        else:
            base_name, _ = os.path.splitext(file_name)
            
            if self._filter_regex.pattern() == "":
                return file_path.lower().endswith(tuple(self.extensions))
            
            name_matches = self._filter_regex.match(base_name).hasMatch()
            return name_matches and file_path.lower().endswith(tuple(self.extensions))

    def flags(self, index):
        """항목을 편집 가능하게 설정합니다."""
        default_flags = super().flags(index)
        if index.isValid():
            return default_flags | Qt.ItemIsEditable
        return default_flags

    def setData(self, index, value, role=Qt.EditRole):
        """파일 이름 변경을 처리합니다."""
        if role == Qt.EditRole and index.isValid():
            source_index = self.mapToSource(index)
            old_path = self.sourceModel().filePath(source_index)
            
            if not os.path.isfile(old_path):
                return False # 폴더 이름 변경은 비활성화

            _, ext = os.path.splitext(old_path)
            new_name = f"{value}{ext}"
            
            dir_path = os.path.dirname(old_path)
            new_path = os.path.join(dir_path, new_name)

            if old_path == new_path:
                return True

            if os.path.exists(new_path):
                QMessageBox.warning(None, "이름 바꾸기 오류", f"같은 이름의 파일이 이미 존재합니다: {new_name}")
                return False

            try:
                os.rename(old_path, new_path)
                
                if old_path in self.favorites:
                    self.favorites.remove(old_path)
                    self.favorites.add(new_path)
                    if self.parent():
                        self.parent().save_favorites()
                
                # 이름 변경 후 선택 유지를 위해 신호 발생
                self.itemRenamed.emit(new_path)
                return True
            except OSError as e:
                QMessageBox.warning(None, "이름 바꾸기 오류", f"파일 이름을 변경할 수 없습니다: {e}")
                return False
        
        return super().setData(index, value, role)

    def setFilterRegularExpression(self, pattern: QRegularExpression):
        self._filter_regex = pattern
        self.invalidateFilter()

    def set_favorites_only_mode(self, enabled):
        """즐겨찾기 보기 모드를 설정합니다."""
        self.favorites_only_mode = enabled
        self.invalidateFilter()


class PraiseSheetViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("물댄동산 악보 뷰어 Pet1 2:9 V2.0")

        self.viewer = None
        self.current_tooltip_index = QModelIndex()
        self.current_playlist_tooltip_item = None
        self.current_preview_path = None

        # --- 경로 설정 ---
        if getattr(sys, 'frozen', False):
            self.app_dir = os.path.dirname(sys.executable)
        else:
            self.app_dir = os.path.dirname(os.path.abspath(__file__))

        # --- 아이콘 설정 ---
        window_icon_path = os.path.join(self.app_dir, "musicsheet.ico")
        if os.path.exists(window_icon_path):
            self.setWindowIcon(QIcon(window_icon_path))
        
        # --- 설정 불러오기 ---
        self.settings_file = os.path.join(self.app_dir, "settings.json")
        self.themes = self.get_themes()
        self.load_settings()

        # --- 즐겨찾기 설정 ---
        self.favorites = set()
        self.favorites_file = os.path.join(self.app_dir, "favorites.json")
        self.load_favorites()
        self.favorites_view_active = False

        # --- 파일 시스템 모델 설정 (악보 & 플레이리스트) ---
        self.image_extensions = [".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"]
        self.all_extensions = self.image_extensions + [".pls"]
        
        self.model = QFileSystemModel()
        self.model.setRootPath(self.sheet_music_path)
        self.model.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot | QDir.Files)
        self.proxy_model = CustomSortFilterProxyModel(self.all_extensions, self.favorites, self)
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy_model.itemRenamed.connect(self.update_selection_after_rename)
        
        self.playlist_model = QFileSystemModel()
        self.playlist_model.setRootPath(self.playlist_path)
        self.playlist_model.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot | QDir.Files)
        self.playlist_proxy_model = CustomSortFilterProxyModel([".pls"], set(), self)
        self.playlist_proxy_model.setSourceModel(self.playlist_model)
        self.playlist_proxy_model.itemRenamed.connect(self.update_selection_after_rename)

        # --- 악보 폴더 설정 UI ---
        self.path_label = QLineEdit(os.path.normpath(self.sheet_music_path))
        self.path_label.setReadOnly(True)
        self.btn_change_folder = QPushButton("폴더 변경")
        self.btn_change_folder.setFixedWidth(80)
        self.btn_change_folder.clicked.connect(self.change_sheet_music_folder)
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("악보 폴더:"))
        path_layout.addWidget(self.path_label)
        path_layout.addWidget(self.btn_change_folder)

        # --- 플레이리스트 폴더 설정 UI ---
        self.playlist_path_label = QLineEdit(os.path.normpath(self.playlist_path))
        self.playlist_path_label.setReadOnly(True)
        self.btn_change_playlist_folder = QPushButton("폴더 변경")
        self.btn_change_playlist_folder.setFixedWidth(88)
        self.btn_change_playlist_folder.clicked.connect(self.change_playlist_folder)
        playlist_path_layout = QHBoxLayout()
        playlist_path_layout.addWidget(QLabel("플레이리스트 폴더:"))
        playlist_path_layout.addWidget(self.playlist_path_label)
        playlist_path_layout.addWidget(self.btn_change_playlist_folder)

        # --- 악보 트리 뷰 설정 ---
        self.tree = QTreeView()
        self.tree.setModel(self.proxy_model)
        self.tree.setRootIndex(
            self.proxy_model.mapFromSource(self.model.index(self.sheet_music_path))
        )
        self.tree.setColumnHidden(1, True)
        self.tree.setColumnHidden(2, True)
        self.tree.setColumnHidden(3, True)
        self.tree.setSelectionMode(QTreeView.SingleSelection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        self.tree.setExpandsOnDoubleClick(True)
        self.tree.doubleClicked.connect(self.handle_tree_double_click)
        self.tree.setMouseTracking(True)
        self.tree.mouseMoveEvent = lambda event: self.handle_tree_mouse_move(event, self.tree)
        self.tree.setEditTriggers(QAbstractItemView.EditKeyPressed)
        
        # --- 플레이리스트 트리 뷰 설정 ---
        self.playlist_tree = QTreeView()
        self.playlist_tree.setModel(self.playlist_proxy_model)
        self.playlist_tree.setRootIndex(
            self.playlist_proxy_model.mapFromSource(self.playlist_model.index(self.playlist_path))
        )
        self.playlist_tree.setColumnHidden(1, True)
        self.playlist_tree.setColumnHidden(2, True)
        self.playlist_tree.setColumnHidden(3, True)
        self.playlist_tree.setSelectionMode(QTreeView.SingleSelection)
        self.playlist_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.playlist_tree.customContextMenuRequested.connect(self.show_playlist_context_menu)
        self.playlist_tree.doubleClicked.connect(self.handle_tree_double_click)
        self.playlist_tree.setMouseTracking(True)
        self.playlist_tree.mouseMoveEvent = lambda event: self.handle_tree_mouse_move(event, self.playlist_tree)
        self.playlist_tree.setEditTriggers(QAbstractItemView.EditKeyPressed)

        # --- [수정] 검색 기능 위젯 (악보 전용) ---
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300)  # 300ms 딜레이
        self.search_timer.timeout.connect(self.perform_search_filter)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("악보 검색...")
        self.search_input.textChanged.connect(self.on_search_text_changed) # 변경
        self.btn_reset_search = QPushButton("초기화")
        self.btn_reset_search.setFixedWidth(80)
        self.btn_reset_search.clicked.connect(self.reset_search_filter)
        search_layout = QHBoxLayout()
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.btn_reset_search)
        
        # --- [수정] 검색 기능 위젯 (플레이리스트 전용) ---
        self.playlist_search_timer = QTimer(self)
        self.playlist_search_timer.setSingleShot(True)
        self.playlist_search_timer.setInterval(300) # 300ms 딜레이
        self.playlist_search_timer.timeout.connect(self.perform_playlist_search_filter)

        self.playlist_search_input = QLineEdit()
        self.playlist_search_input.setPlaceholderText("플레이리스트 검색...")
        self.playlist_search_input.textChanged.connect(self.playlist_search_timer.start) # 변경
        self.btn_reset_playlist_search = QPushButton("초기화")
        self.btn_reset_playlist_search.setFixedWidth(80)
        self.btn_reset_playlist_search.clicked.connect(self.reset_playlist_search_filter)
        playlist_search_layout = QHBoxLayout()
        playlist_search_layout.addWidget(self.playlist_search_input)
        playlist_search_layout.addWidget(self.btn_reset_playlist_search)

        # --- 정렬 기능 위젯 (플레이리스트 전용) ---
        self.playlist_sort_combo = QComboBox()
        self.playlist_sort_combo.addItems([
            "수정날짜순 (최신)", "수정날짜순 (오래된)",
            "이름순 (오름차순)", "이름순 (내림차순)"
        ])
        self.playlist_sort_combo.setCurrentText("수정날짜순 (최신)")
        self.playlist_sort_combo.currentTextChanged.connect(self.change_playlist_sort_order)
        playlist_sort_layout = QHBoxLayout()
        playlist_sort_layout.addWidget(QLabel("정렬:"))
        playlist_sort_layout.addWidget(self.playlist_sort_combo)

        # --- 타이틀 위젯들 ---
        title_font = QFont("맑은 고딕", 16, QFont.Bold)
        self.tree_title = QLabel("악보 선택")
        self.tree_title.setFont(title_font)
        self.tree_title.setAlignment(Qt.AlignCenter)
        self.preview_title = QLabel("악보 미리보기")
        self.preview_title.setFont(title_font)
        self.preview_title.setAlignment(Qt.AlignCenter)
        self.list_title = QLabel("선택된 찬양")
        self.list_title.setFont(title_font)
        self.list_title.setAlignment(Qt.AlignCenter)

        # --- 미리보기 창 위젯 구성 변경 ---
        self.preview_label = QLabel("파일을 선택하여 미리보세요.")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setFont(QFont("맑은 고딕", 12))
        self.preview_scroll_area = QScrollArea()
        self.preview_scroll_area.setWidgetResizable(True)
        self.preview_scroll_area.setWidget(self.preview_label)

        self.preview_list_widget = QListWidget()
        self.preview_list_widget.itemDoubleClicked.connect(self.add_preview_list_item_to_main_list)
        self.preview_list_widget.setMouseTracking(True)
        self.preview_list_widget.mouseMoveEvent = self.playlist_preview_mouse_move_event
        
        self.preview_container = QWidget()
        self.preview_stack = QStackedLayout(self.preview_container)
        self.preview_stack.addWidget(self.preview_scroll_area)
        self.preview_stack.addWidget(self.preview_list_widget)

        self.btn_show_single = QPushButton("이 곡 쇼하기 (F6)")
        self.btn_show_single.setShortcut(Qt.Key_F6)
        self.btn_show_single.clicked.connect(self.start_single_song_show)

        preview_layout = QVBoxLayout()
        preview_layout.addWidget(self.preview_title)
        preview_layout.addWidget(self.preview_container)
        preview_layout.addWidget(self.btn_show_single)
        
        # --- 즐겨찾기 버튼 (악보 전용) ---
        self.btn_add_favorite = QPushButton("즐겨찾기 추가")
        self.btn_add_favorite.clicked.connect(self.add_current_to_favorites)
        self.btn_remove_favorite = QPushButton("즐겨찾기 삭제")
        self.btn_remove_favorite.clicked.connect(self.remove_current_from_favorites)
        self.btn_toggle_favorites_view = QPushButton("즐겨찾기 보기")
        self.btn_toggle_favorites_view.setCheckable(True)
        self.btn_toggle_favorites_view.clicked.connect(self.toggle_favorites_view)
        favorites_button_layout = QHBoxLayout()
        favorites_button_layout.addWidget(self.btn_add_favorite)
        favorites_button_layout.addWidget(self.btn_remove_favorite)
        favorites_button_layout.addWidget(self.btn_toggle_favorites_view)

        self.btn_add_selected = QPushButton("선택 항목 추가")
        self.btn_add_selected.clicked.connect(self.add_selected_file_single)

        # --- 좌측 레이아웃 구성 변경 (Splitter 사용) ---
        self.status_bar_label = QLabel()
        splitter = QSplitter(Qt.Vertical)

        top_container = QWidget()
        top_layout = QVBoxLayout(top_container)
        top_layout.setContentsMargins(0,0,0,0)
        top_layout.addLayout(path_layout)
        top_layout.addLayout(search_layout)
        top_layout.addWidget(self.tree)
        top_layout.addWidget(self.status_bar_label)
        top_layout.addLayout(favorites_button_layout)
        top_layout.addWidget(self.btn_add_selected)

        bottom_container = QWidget()
        bottom_layout = QVBoxLayout(bottom_container)
        bottom_layout.setContentsMargins(0,0,0,0)
        playlist_title = QLabel("플레이리스트")
        playlist_title.setFont(QFont("맑은 고딕", 12, QFont.Bold))
        playlist_title.setAlignment(Qt.AlignCenter)
        bottom_layout.addWidget(playlist_title)
        bottom_layout.addLayout(playlist_path_layout)
        bottom_layout.addLayout(playlist_search_layout)
        bottom_layout.addLayout(playlist_sort_layout)
        bottom_layout.addWidget(self.playlist_tree)

        splitter.addWidget(top_container)
        splitter.addWidget(bottom_container)
        splitter.setSizes([400, 200])

        tree_layout = QVBoxLayout()
        tree_layout.addWidget(self.tree_title)
        tree_layout.addWidget(splitter)

        # --- 선택된 찬양 리스트 위젯 (우측) ---
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        self.list_widget.setDragEnabled(True)
        self.list_widget.setAcceptDrops(True)
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        self.list_widget.itemDoubleClicked.connect(self.handle_list_double_click)
        list_font = QFont()
        list_font.setPointSize(12)
        self.list_widget.setFont(list_font)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self.show_list_widget_context_menu)
        
        # --- 우측 하단 버튼 및 컨트롤 ---
        self.btn_delete = QPushButton("선택 삭제")
        self.btn_delete.clicked.connect(self.delete_selected_items)
        self.btn_delete_all = QPushButton("전체 삭제")
        self.btn_delete_all.clicked.connect(self.delete_all_items)
        show_title_font = QFont("맑은 고딕", 14, QFont.Bold)
        self.show_title_label = QLabel("쇼 시작")
        self.show_title_label.setFont(show_title_font)
        self.show_title_label.setAlignment(Qt.AlignCenter)
        self.btn_start_from_first = QPushButton("처음 곡부터 (F5)")
        self.btn_start_from_first.setShortcut(Qt.Key_F5)
        self.btn_start_from_first.setStyleSheet("padding: 10px; font-size: 11pt;")
        self.btn_start_from_current = QPushButton("현재 곡부터 (Shift+F5)")
        self.btn_start_from_current.setShortcut(QKeySequence("Shift+F5"))
        self.btn_start_from_current.setStyleSheet("padding: 10px; font-size: 11pt;")
        self.btn_start_from_first.clicked.connect(self.start_show)
        self.btn_start_from_current.clicked.connect(self.start_show_from_current)
        self.btn_save_list = QPushButton("리스트 저장")
        self.btn_load_list = QPushButton("리스트 불러오기")
        self.btn_move_up = QPushButton("↑ 위로 이동")
        self.btn_move_down = QPushButton("↓ 아래로 이동")
        self.btn_move_top = QPushButton("▲ 맨 위로 이동")
        self.btn_move_bottom = QPushButton("▼ 맨 아래로 이동")
        self.btn_save_list.clicked.connect(self.save_list)
        self.btn_load_list.clicked.connect(self.load_list)
        self.btn_move_up.clicked.connect(self.move_item_up)
        self.btn_move_down.clicked.connect(self.move_item_down)
        self.btn_move_top.clicked.connect(self.move_item_top)
        self.btn_move_bottom.clicked.connect(self.move_item_bottom)
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(self.themes.keys())
        self.theme_combo.setCurrentText(self.current_theme)
        self.theme_combo.currentTextChanged.connect(self.set_theme)
        theme_layout = QHBoxLayout()
        theme_layout.addWidget(QLabel("테마:"))
        theme_layout.addWidget(self.theme_combo)
        self.zoom_label = QLabel()
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(50, 100)
        self.zoom_slider.setValue(self.initial_zoom_percentage)
        self.zoom_slider.valueChanged.connect(self.update_zoom_label)
        self.update_zoom_label(self.initial_zoom_percentage)
        zoom_layout = QHBoxLayout()
        zoom_layout.addWidget(QLabel("초기 화면 크기:"))
        zoom_layout.addWidget(self.zoom_slider)
        zoom_layout.addWidget(self.zoom_label)

        # --- [새로 추가된 스크롤 민감도 위젯] ---
        self.scroll_label = QLabel()
        self.scroll_slider = QSlider(Qt.Horizontal)
        self.scroll_slider.setRange(10, 150) # 10px ~ 150px 범위
        self.scroll_slider.setValue(self.scroll_sensitivity) # load_settings에서 불러온 값
        self.scroll_slider.valueChanged.connect(self.update_scroll_label)
        self.update_scroll_label(self.scroll_sensitivity)
        scroll_layout = QHBoxLayout()
        scroll_layout.addWidget(QLabel("스크롤 민감도:"))
        scroll_layout.addWidget(self.scroll_slider)
        scroll_layout.addWidget(self.scroll_label)
        # --- [추가 끝] ---

        button_layout1 = QHBoxLayout()
        button_layout1.addWidget(self.btn_move_top)
        button_layout1.addWidget(self.btn_move_up)
        button_layout1.addWidget(self.btn_move_down)
        button_layout1.addWidget(self.btn_move_bottom)
        button_layout2 = QHBoxLayout()
        button_layout2.addWidget(self.btn_delete)
        button_layout2.addWidget(self.btn_delete_all)
        button_layout2.addWidget(self.btn_save_list)
        button_layout2.addWidget(self.btn_load_list)
        show_layout = QVBoxLayout()
        show_layout.setSpacing(5)
        show_layout.addWidget(self.show_title_label)
        show_layout.addWidget(self.btn_start_from_first)
        show_layout.addWidget(self.btn_start_from_current)
        shortcut_group_box = QGroupBox("쇼 화면 단축키 안내")
        shortcut_layout = QVBoxLayout(shortcut_group_box)
        shortcut_label = QLabel()
        shortcut_text = """
        <b>- 다음:</b> PgDn, →, 마우스 좌클릭<br>
        <b>- 이전:</b> PgUp, ←, 마우스 우클릭<br>
        <b>- 스크롤:</b> ↑, ↓, 마우스 휠<br>
        <b>- 확대/축소:</b> +, - / Ctrl+마우스 휠<br>
        <b>- 너비 맞춤:</b> * (별표)<br>
        <b>- 높이 맞춤:</b> 0 (숫자)<br>
        <b>- 종료:</b> Esc
        """
        shortcut_label.setText(shortcut_text)
        shortcut_label.setWordWrap(True)
        shortcut_label.setAlignment(Qt.AlignLeft)
        shortcut_layout.addWidget(shortcut_label)

        right_layout = QVBoxLayout()
        right_layout.addWidget(self.list_title)
        right_layout.addWidget(self.list_widget)
        right_layout.addWidget(shortcut_group_box)
        right_layout.addLayout(button_layout1)
        right_layout.addLayout(button_layout2)
        right_layout.addLayout(theme_layout)
        right_layout.addLayout(zoom_layout)
        right_layout.addLayout(scroll_layout) # --- [스크롤 레이아웃 추가] ---
        right_layout.addLayout(show_layout)

        main_layout = QHBoxLayout()
        main_layout.addLayout(tree_layout, 2)
        main_layout.addLayout(preview_layout, 3)
        main_layout.addLayout(right_layout, 2)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        self.tree.selectionModel().currentChanged.connect(
            lambda current, prev: self.preview_selected_file(current, self.tree)
        )
        self.playlist_tree.selectionModel().currentChanged.connect(
            lambda current, prev: self.preview_selected_file(current, self.playlist_tree)
        )
        self.apply_theme(self.current_theme)

        self.model.directoryLoaded.connect(self.update_file_count)
        self.update_file_count(self.sheet_music_path)
        
        self.change_playlist_sort_order(self.playlist_sort_combo.currentText())

    def update_selection_after_rename(self, new_path):
        """파일 이름 변경 후, 해당 항목을 다시 선택합니다."""
        # 경로에 따라 어떤 트리와 모델을 사용할지 결정
        if self.sheet_music_path in new_path:
            tree = self.tree
            proxy_model = self.proxy_model
            source_model = self.model
        elif self.playlist_path in new_path:
            tree = self.playlist_tree
            proxy_model = self.playlist_proxy_model
            source_model = self.playlist_model
        else:
            return

        # 새 경로에 해당하는 인덱스를 찾아 현재 인덱스로 설정
        source_index = source_model.index(new_path)
        if source_index.isValid():
            proxy_index = proxy_model.mapFromSource(source_index)
            if proxy_index.isValid():
                tree.setCurrentIndex(proxy_index)
    
    def playlist_tree_mouse_move_event(self, event):
        """플레이리스트 트리에서 마우스 이동 시 툴팁을 표시합니다."""
        index = self.playlist_tree.indexAt(event.position().toPoint())
        if index.isValid() and index != self.current_tooltip_index:
            self.current_tooltip_index = index
            source_index = self.playlist_proxy_model.mapToSource(index)
            path = self.playlist_model.filePath(source_index)

            if os.path.isfile(path) and path.lower().endswith(".pls"):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        song_list = json.load(f)
                    if song_list:
                        song_names = [os.path.splitext(os.path.basename(s))[0] for s in song_list]
                        tooltip_text = "<b>플레이리스트:</b><br>" + "<br>".join(f"- {name}" for name in song_names)
                    else:
                        tooltip_text = "비어 있는 플레이리스트입니다."
                    QToolTip.showText(event.globalPosition().toPoint() + QPoint(20, 20), tooltip_text, self.playlist_tree)
                except Exception:
                    QToolTip.showText(event.globalPosition().toPoint() + QPoint(20, 20), "플레이리스트를 읽을 수 없습니다.", self.playlist_tree)
            else:
                QToolTip.hideText()
        elif not index.isValid():
            QToolTip.hideText()
            self.current_tooltip_index = QModelIndex()
        super(QTreeView, self.playlist_tree).mouseMoveEvent(event)


    def playlist_preview_mouse_move_event(self, event):
        """플레이리스트 미리보기 위젯에서 마우스 이동 시 툴팁을 표시합니다."""
        item = self.preview_list_widget.itemAt(event.position().toPoint())

        if item is not None and item != self.current_playlist_tooltip_item:
            self.current_playlist_tooltip_item = item
            path = item.data(Qt.UserRole)

            if path and os.path.isfile(path) and path.lower().endswith(tuple(self.image_extensions)):
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    fixed_width = 250
                    scaled = pixmap.scaledToWidth(fixed_width, Qt.SmoothTransformation)
                    tooltip = (
                        f'<img style="margin:0;padding:0;" src="{path}"'
                        f' width="{scaled.width()}" height="{scaled.height()}"/>'
                    )
                    QToolTip.showText(
                        event.globalPosition().toPoint() + QPoint(20, 20),
                        tooltip, self.preview_list_widget
                    )
                else:
                    QToolTip.hideText()
            else:
                QToolTip.hideText()
        
        elif item is None:
            QToolTip.hideText()
            self.current_playlist_tooltip_item = None
        
        QListWidget.mouseMoveEvent(self.preview_list_widget, event)

    def add_preview_list_item_to_main_list(self, item):
        """미리보기 리스트의 항목을 메인 리스트에 추가합니다."""
        path = item.data(Qt.UserRole)
        if path and os.path.isfile(path):
            base_name = os.path.splitext(os.path.basename(path))[0]
            item_text = f"⭐ {base_name}" if path in self.favorites else base_name
            new_item = QListWidgetItem(f"🎼 {item_text}")
            new_item.setData(Qt.UserRole, path)
            self.list_widget.addItem(new_item)
        
    def start_single_song_show(self):
        """현재 미리보기 중인 한 곡만으로 쇼를 시작합니다."""
        if not self.current_preview_path:
            QMessageBox.warning(self, "알림", "쇼를 시작할 곡을 먼저 선택해주세요.")
            return

        is_image = self.current_preview_path.lower().endswith(tuple(self.image_extensions))
        if not os.path.isfile(self.current_preview_path) or not is_image:
            QMessageBox.warning(self, "알림", "이미지 파일만 쇼를 시작할 수 있습니다. (.pls 파일 등은 불가)")
            return

        paths = [self.current_preview_path]
        
        self.viewer = FullScreenViewer(
            paths, self.initial_zoom_percentage, start_index=0,
            scroll_sensitivity=self.scroll_sensitivity # --- [인자 추가] ---
        )
        self.viewer.showFullScreen()

    def update_file_count(self, path):
        """Updates the status bar with the total number of files in the view."""
        total_files = 0
        root_index = self.tree.rootIndex()
        if root_index.isValid():
            total_files = self.count_visible_items(root_index)

        self.status_bar_label.setText(f"총 {total_files}개의 악보")

    def count_visible_items(self, parent_index):
        """Recursively counts visible files in the tree view."""
        count = 0
        model = self.tree.model()
        num_rows = model.rowCount(parent_index)

        for row in range(num_rows):
            index = model.index(row, 0, parent_index)
            if not self.tree.isRowHidden(row, parent_index):
                source_index = self.proxy_model.mapToSource(index)
                file_path = self.model.filePath(source_index)
                if os.path.isfile(file_path):
                    count += 1
                if self.model.isDir(source_index):
                    if self.tree.isExpanded(index):
                        count += self.count_visible_items(index)
        return count

    def resizeEvent(self, event):
        """창 크기 조절 시 미리보기 이미지 업데이트"""
        super().resizeEvent(event)
        if self.current_preview_path and self.preview_stack.currentWidget() == self.preview_scroll_area:
            self.update_preview_panel(self.current_preview_path)

    def keyPressEvent(self, event):
        """'선택된 찬양' 리스트에서 Delete 키를 눌러 항목을 삭제합니다."""
        if self.list_widget.hasFocus() and event.key() == Qt.Key_Delete:
            self.delete_selected_items()
        else:
            super().keyPressEvent(event)

    def get_themes(self):
        """색상 테마를 정의합니다."""
        return {
            "그린": {
                "base": "#F0FFF0", "window": "#E6F5E6", "text": "#003300",
                "button": "#90EE90", "button_text": "#003300",
                "highlight": "#3CB371", "highlight_text": "#FFFFFF",
                "border": "#2E8B57",
            },
            "기본 (밝게)": {
                "base": "#FFFFFF", "window": "#FFFFFF", "text": "#000000",
                "button": "#F5F5F5", "button_text": "#000000",
                "highlight": "#D3D3D3", "highlight_text": "#000000",
                "border": "#CCCCCC",
            },
            "어둡게": {
                "base": "#3E3E3E", "window": "#2D2D2D", "text": "#E0E0E0",
                "button": "#555555", "button_text": "#E0E0E0",
                "highlight": "#BB86FC", "highlight_text": "#000000",
                "border": "#1E1E1E",
            },
            "클래식 블루": {
                "base": "#EAF2F8", "window": "#D4E6F1", "text": "#1A5276",
                "button": "#A9CCE3", "button_text": "#154360",
                "highlight": "#5DADE2", "highlight_text": "#FFFFFF",
                "border": "#A9CCE3",
            }
        }

    def set_theme(self, theme_name):
        """콤보박스에서 선택된 테마를 적용합니다."""
        self.current_theme = theme_name
        self.apply_theme(theme_name)

    def apply_theme(self, theme_name):
        """애플리케이션에 색상 테마를 적용합니다."""
        theme = self.themes.get(theme_name, self.themes["그린"])
        
        stylesheet = f"""
            QWidget {{
                background-color: {theme['window']};
                color: {theme['text']};
            }}
            QTreeView, QListWidget, QLineEdit, QScrollArea, QGroupBox {{
                background-color: {theme['base']};
                border: 1px solid {theme['border']};
            }}
            QGroupBox {{
                margin-top: 10px;
                font-weight: bold;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top center;
                padding: 0 3px;
            }}
            QTreeView::item:hover, QListWidget::item:hover {{
                background-color: {theme['highlight']};
                color: {theme['highlight_text']};
            }}
            QTreeView::item:selected, QListWidget::item:selected {{
                background-color: {theme['highlight']};
                color: {theme['highlight_text']};
            }}
            QPushButton {{
                background-color: {theme['button']};
                color: {theme['button_text']};
                border-width: 2px;
                border-style: outset;
                border-color: {theme['border']};
                border-radius: 5px;
                padding: 5px;
            }}
            QPushButton:hover {{
                background-color: {theme['highlight']};
                color: {theme['highlight_text']};
            }}
            QPushButton:pressed {{
                background-color: {theme['base']};
                border-style: inset;
            }}
            QLabel, QCheckBox {{
                color: {theme['text']};
                border: none;
                background-color: transparent;
            }}
            QToolTip {{
                background-color: {theme['base']};
                color: {theme['text']};
                border: 1px solid {theme['border']};
            }}
        """
        self.setStyleSheet(stylesheet)
        
        self.btn_start_from_first.setStyleSheet("padding: 10px; font-size: 11pt;")
        self.btn_start_from_current.setStyleSheet("padding: 10px; font-size: 11pt;")
        
        self.preview_label.setStyleSheet(f"border: 1px solid {theme['border']};")


    def update_zoom_label(self, value):
        """슬라이더 값 변경 시 줌 레이블 업데이트 및 설정 값 저장"""
        self.initial_zoom_percentage = value
        self.zoom_label.setText(f"{value}%")

    def update_scroll_label(self, value):
        """슬라이더 값 변경 시 스크롤 레이블 업데이트 및 설정 값 저장"""
        self.scroll_sensitivity = value
        self.scroll_label.setText(f"{value}px")

    def load_settings(self):
        """JSON 파일에서 설정을 불러옵니다."""
        self.sheet_music_path = "c:\\songs"
        self.playlist_path = "c:\\songs\\playlist"
        if not os.path.exists(self.playlist_path):
            os.makedirs(self.playlist_path)
        default_theme = "그린"
        self.scroll_sensitivity = 30 # --- [기본값 추가] ---
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    self.initial_zoom_percentage = settings.get('initial_zoom', 80)
                    self.sheet_music_path = settings.get('sheet_music_path', self.sheet_music_path)
                    self.playlist_path = settings.get('playlist_path', self.playlist_path)
                    self.current_theme = settings.get('current_theme', default_theme)
                    self.scroll_sensitivity = settings.get('scroll_sensitivity', 30) # --- [설정 불러오기 추가] ---
            else:
                self.initial_zoom_percentage = 80
        except (json.JSONDecodeError, TypeError):
            self.initial_zoom_percentage = 80
            self.current_theme = default_theme
            self.scroll_sensitivity = 30 # --- [예외 처리 시 기본값 추가] ---
            QMessageBox.warning(self, "설정 로드 오류", "설정 파일을 불러오는 데 실패했습니다. 기본값으로 시작합니다.")

    def save_settings(self):
        """현재 설정을 JSON 파일에 저장합니다."""
        settings = {
            'initial_zoom': self.initial_zoom_percentage,
            'sheet_music_path': self.sheet_music_path,
            'playlist_path': self.playlist_path,
            'current_theme': self.current_theme,
            'scroll_sensitivity': self.scroll_sensitivity # --- [설정 저장 추가] ---
        }
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            QMessageBox.critical(self, "설정 저장 오류", f"설정을 저장하는 중 오류 발생: {e}")

    def closeEvent(self, event):
        """애플리케이션 종료 시 설정을 저장합니다."""
        self.save_settings()
        super().closeEvent(event)

    def change_sheet_music_folder(self):
        """악보가 저장된 루트 폴더를 변경합니다."""
        folder_path = QFileDialog.getExistingDirectory(self, "악보 폴더 선택", self.sheet_music_path)
        if folder_path and folder_path != self.sheet_music_path:
            self.sheet_music_path = folder_path
            self.path_label.setText(os.path.normpath(self.sheet_music_path))
            self.model.setRootPath(self.sheet_music_path)
            self.tree.setRootIndex(self.proxy_model.mapFromSource(self.model.index(self.sheet_music_path)))
            self.save_settings()

    def change_playlist_folder(self):
        """플레이리스트가 저장된 루트 폴더를 변경합니다."""
        folder_path = QFileDialog.getExistingDirectory(self, "플레이리스트 폴더 선택", self.playlist_path)
        if folder_path and folder_path != self.playlist_path:
            self.playlist_path = folder_path
            self.playlist_path_label.setText(os.path.normpath(self.playlist_path))
            self.playlist_model.setRootPath(self.playlist_path)
            self.playlist_tree.setRootIndex(self.playlist_proxy_model.mapFromSource(self.playlist_model.index(self.playlist_path)))
            self.save_settings()

    # --- [수정] 새 타이머 슬롯 함수 1 ---
    def on_search_text_changed(self, text):
        """악보 검색 텍스트 변경 시 호출됩니다. 즐겨찾기 모드인지 확인하고 타이머를 시작합니다."""
        if self.favorites_view_active:
            # clear()가 textChanged를 다시 호출하는 것을 방지
            self.search_input.blockSignals(True)
            self.search_input.clear()
            self.search_input.blockSignals(False)
            
            QMessageBox.information(self, "알림", "즐겨찾기 보기 모드에서는 검색할 수 없습니다.\n'전체 보기'로 전환 후 검색해주세요.")
            return
        
        # 즐겨찾기 모드가 아니면 타이머 시작 (딜레이 후 perform_search_filter 호출)
        self.search_timer.start()

    # --- [수정] 새 타이머 슬롯 함수 2 ---
    def perform_search_filter(self):
        """search_timer가 만료되면 실제 검색 필터를 적용합니다."""
        text = self.search_input.text()
        self.apply_search_filter(text) # 기존 필터 함수 호출

    # --- [수정] 새 타이머 슬롯 함수 3 ---
    def perform_playlist_search_filter(self):
        """playlist_search_timer가 만료되면 실제 플레이리스트 검색 필터를 적용합니다."""
        text = self.playlist_search_input.text()
        self.apply_playlist_search_filter(text) # 기존 필터 함수 호출

    # --- [수정] apply_search_filter에서 즐겨찾기 확인 로직 제거 ---
    def apply_search_filter(self, text):
        # if self.favorites_view_active: ... (이 블록은 on_search_text_changed로 이동함)

        keywords = text.strip().split()
        if not keywords:
            pattern = ""
        else:
            pattern = "".join([f"(?=.*{re.escape(keyword)})" for keyword in keywords])

        self.proxy_model.setFilterRegularExpression(
            QRegularExpression(pattern, QRegularExpression.CaseInsensitiveOption)
        )
        self.tree.setRootIndex(
            self.proxy_model.mapFromSource(self.model.index(self.model.rootPath()))
        )
        self.update_file_count(self.sheet_music_path)
    
    def apply_playlist_search_filter(self, text):
        """플레이리스트 트리에 검색 필터를 적용합니다."""
        keywords = text.strip().split()
        if not keywords:
            pattern = ""
        else:
            pattern = "".join([f"(?=.*{re.escape(keyword)})" for keyword in keywords])

        self.playlist_proxy_model.setFilterRegularExpression(
            QRegularExpression(pattern, QRegularExpression.CaseInsensitiveOption)
        )
        self.playlist_tree.setRootIndex(
            self.playlist_proxy_model.mapFromSource(self.playlist_model.index(self.playlist_model.rootPath()))
        )

    def reset_search_filter(self):
        self.search_input.clear()

    def reset_playlist_search_filter(self):
        """플레이리스트 검색을 초기화합니다."""
        self.playlist_search_input.clear()
        
    def change_playlist_sort_order(self, text):
        """플레이리스트 트리의 정렬 순서를 변경합니다."""
        # 0: 이름, 3: 수정날짜
        if text == "이름순 (오름차순)":
            self.playlist_proxy_model.sort(0, Qt.AscendingOrder)
        elif text == "이름순 (내림차순)":
            self.playlist_proxy_model.sort(0, Qt.DescendingOrder)
        elif text == "수정날짜순 (최신)":
            self.playlist_proxy_model.sort(3, Qt.DescendingOrder)
        elif text == "수정날짜순 (오래된)":
            self.playlist_proxy_model.sort(3, Qt.AscendingOrder)

    def handle_tree_mouse_move(self, event, tree):
        """두 트리 뷰의 마우스 이동 이벤트를 공통으로 처리하여 툴팁을 표시합니다."""
        if tree == self.tree:
            proxy_model = self.proxy_model
            source_model = self.model
        elif tree == self.playlist_tree:
            proxy_model = self.playlist_proxy_model
            source_model = self.playlist_model
        else:
            return

        index = tree.indexAt(event.position().toPoint())
        if index.isValid() and index != self.current_tooltip_index:
            self.current_tooltip_index = index
            source_index = proxy_model.mapToSource(index)
            path = source_model.filePath(source_index)

            if os.path.isfile(path):
                if path.lower().endswith(tuple(self.image_extensions)):
                    pixmap = QPixmap(path)
                    if not pixmap.isNull():
                        fixed_width = 250
                        scaled = pixmap.scaledToWidth(fixed_width, Qt.SmoothTransformation)
                        tooltip = (
                            f'<img style="margin:0;padding:0;" src="{path}"'
                            f' width="{scaled.width()}" height="{scaled.height()}"/>'
                        )
                        QToolTip.showText(event.globalPosition().toPoint() + QPoint(20, 20), tooltip, tree)
                    else:
                        QToolTip.hideText()
                elif path.lower().endswith(".pls"):
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            song_list = json.load(f)
                        if song_list:
                            song_names = [os.path.splitext(os.path.basename(s))[0] for s in song_list]
                            tooltip_text = "<b>플레이리스트:</b><br>" + "<br>".join(f"- {name}" for name in song_names)
                        else:
                            tooltip_text = "비어 있는 플레이리스트입니다."
                        QToolTip.showText(event.globalPosition().toPoint() + QPoint(20, 20), tooltip_text, tree)
                    except Exception:
                        QToolTip.showText(event.globalPosition().toPoint() + QPoint(20, 20), "플레이리스트를 읽을 수 없습니다.", tree)
                else:
                    QToolTip.hideText()
            else:
                QToolTip.hideText()
        elif not index.isValid():
            QToolTip.hideText()
            self.current_tooltip_index = QModelIndex()
        QTreeView.mouseMoveEvent(tree, event)

    def show_context_menu(self, pos):
        """악보 트리에서 마우스 우클릭 시 컨텍스트 메뉴를 표시합니다."""
        index = self.tree.indexAt(pos)
        if not index.isValid():
            return

        self.tree.setCurrentIndex(index)
        source_index = self.proxy_model.mapToSource(index)
        path = self.model.filePath(source_index)
        is_file = os.path.isfile(path)
        
        menu = QMenu()
        
        if is_file:
            is_image = path.lower().endswith(tuple(self.image_extensions))
            if is_image:
                action_show_single = QAction("이 곡 쇼하기", self)
                action_show_single.triggered.connect(self.start_single_song_show)
                menu.addAction(action_show_single)

            action_add_to_list = QAction("선택 항목 추가", self)
            action_add_to_list.triggered.connect(self.add_selected_file_single)
            menu.addAction(action_add_to_list)
            menu.addSeparator()

            if path in self.favorites:
                action_remove_favorite = QAction("즐겨찾기에서 삭제", self)
                action_remove_favorite.triggered.connect(self.remove_current_from_favorites)
                menu.addAction(action_remove_favorite)
            else:
                action_add_favorite = QAction("즐겨찾기에 추가", self)
                action_add_favorite.triggered.connect(self.add_current_to_favorites)
                menu.addAction(action_add_favorite)
            
            menu.addSeparator()
            action_rename = QAction("이름 바꾸기", self)
            action_rename.triggered.connect(lambda: self.tree.edit(index))
            menu.addAction(action_rename)

        if menu.actions():
            menu.exec(self.tree.viewport().mapToGlobal(pos))
            
    def show_playlist_context_menu(self, pos):
        """플레이리스트 트리에서 마우스 우클릭 시 컨텍스트 메뉴를 표시합니다."""
        index = self.playlist_tree.indexAt(pos)
        if not index.isValid():
            return

        self.playlist_tree.setCurrentIndex(index)
        source_index = self.playlist_proxy_model.mapToSource(index)
        path = self.playlist_model.filePath(source_index)
        
        if not os.path.isfile(path):
            return

        menu = QMenu()
        
        action_add_to_list = QAction("목록에 추가하기", self)
        action_add_to_list.triggered.connect(lambda: self._add_paths_from_pls(path))
        menu.addAction(action_add_to_list)
        
        menu.addSeparator()
        
        action_rename = QAction("이름 바꾸기", self)
        action_rename.triggered.connect(lambda: self.playlist_tree.edit(index))
        menu.addAction(action_rename)
        
        action_delete = QAction("삭제", self)
        action_delete.triggered.connect(lambda: self.delete_playlist_file(path))
        menu.addAction(action_delete)

        menu.exec(self.playlist_tree.viewport().mapToGlobal(pos))
        
    def delete_playlist_file(self, path):
        """플레이리스트 파일을 디스크에서 삭제합니다."""
        reply = QMessageBox.question(
            self, '파일 삭제 확인', 
            f"'{os.path.basename(path)}' 파일을 정말로 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                os.remove(path)
            except OSError as e:
                QMessageBox.critical(self, "파일 삭제 오류", f"파일을 삭제하는 중 오류가 발생했습니다: {e}")
    
    def load_favorites(self):
        """JSON 파일에서 즐겨찾기 목록을 불러옵니다."""
        try:
            if os.path.exists(self.favorites_file):
                with open(self.favorites_file, 'r', encoding='utf-8') as f:
                    self.favorites = set(json.load(f))
        except (json.JSONDecodeError, TypeError):
            self.favorites = set()
            QMessageBox.warning(self, "즐겨찾기 로드 오류", "즐겨찾기 파일을 불러오는 데 실패했습니다.")


    def save_favorites(self):
        """현재 즐겨찾기 목록을 JSON 파일에 저장합니다."""
        try:
            with open(self.favorites_file, 'w', encoding='utf-8') as f:
                json.dump(list(self.favorites), f, indent=4)
        except Exception as e:
            QMessageBox.critical(self, "즐겨찾기 저장 오류", f"즐겨찾기를 저장하는 중 오류 발생: {e}")

    def add_current_to_favorites(self):
        """트리 뷰에서 현재 선택된 파일을 즐겨찾기에 추가합니다."""
        index = self.tree.currentIndex()
        if not index.isValid():
            return
        
        source_index = self.proxy_model.mapToSource(index)
        path = self.model.filePath(source_index)

        if os.path.isfile(path):
            self.favorites.add(path)
            self.save_favorites()
            self.proxy_model.invalidate()
        else:
            QMessageBox.warning(self, "알림", "폴더는 즐겨찾기에 추가할 수 없습니다.")

    def remove_current_from_favorites(self):
        """트리 뷰에서 현재 선택된 파일을 즐겨찾기에서 제거합니다."""
        index = self.tree.currentIndex()
        if not index.isValid():
            return

        source_index = self.proxy_model.mapToSource(index)
        path = self.model.filePath(source_index)

        if os.path.isfile(path):
            self.favorites.discard(path)
            self.save_favorites()
            self.proxy_model.invalidate()
        else:
            QMessageBox.warning(self, "알림", "폴더는 즐겨찾기에서 제거할 수 없습니다.")

    def toggle_favorites_view(self, checked):
        """즐겨찾기 보기 모드를 토글합니다."""
        self.favorites_view_active = checked
        if checked:
            self.btn_toggle_favorites_view.setText("전체 보기")
            self.search_input.setEnabled(False)
            self.btn_reset_search.setEnabled(False)
        else:
            self.btn_toggle_favorites_view.setText("즐겨찾기 보기")
            self.search_input.setEnabled(True)
            self.btn_reset_search.setEnabled(True)
        
        self.proxy_model.set_favorites_only_mode(checked)
        self.tree.setRootIndex(
            self.proxy_model.mapFromSource(self.model.index(self.model.rootPath()))
        )
        self.tree.expandAll()
        self.update_file_count(self.sheet_music_path)

    def _add_paths_from_pls(self, pls_path):
        """PLS 파일에서 경로를 읽어 리스트 위젯에 추가합니다."""
        try:
            with open(pls_path, 'r', encoding='utf-8') as f:
                relative_paths = json.load(f)
                for rel_p in relative_paths:
                    p = os.path.normpath(os.path.join(self.sheet_music_path, rel_p))
                    if os.path.exists(p) and os.path.isfile(p) and p.lower().endswith(tuple(self.image_extensions)):
                        base_name = os.path.splitext(os.path.basename(p))[0]
                        item_text = f"⭐ {base_name}" if p in self.favorites else base_name
                        item = QListWidgetItem(f"🎼 {item_text}")
                        item.setData(Qt.UserRole, p)
                        self.list_widget.addItem(item)
                    else:
                        print(f"경로를 찾을 수 없거나 이미지 파일이 아님 (PLS 파일 내부): {p}")
        except json.JSONDecodeError:
            QMessageBox.critical(self, "오류", f"올바른 .pls 파일이 아닙니다: {pls_path}")
        except Exception as e:
            QMessageBox.critical(self, "오류", f".pls 파일을 불러오는 중 오류 발생: {e}")

    def add_selected_file_single(self):
        idx = self.tree.currentIndex()
        if not idx.isValid() or idx.column() != 0:
            return

        source_index = self.proxy_model.mapToSource(idx)
        path = self.model.filePath(source_index)

        if os.path.isfile(path):
            if path.lower().endswith(".pls"):
                self._add_paths_from_pls(path)
            elif path.lower().endswith(tuple(self.image_extensions)):
                base_name = os.path.splitext(os.path.basename(path))[0]
                item_text = f"⭐ {base_name}" if path in self.favorites else base_name
                item = QListWidgetItem(f"🎼 {item_text}")
                item.setData(Qt.UserRole, path)
                self.list_widget.addItem(item)
        elif os.path.isdir(path):
            QMessageBox.information(self, "정보", "폴더는 추가할 수 없습니다. 파일을 선택해 주세요.")

    def handle_tree_double_click(self, index):
        tree = self.sender()
        if tree == self.tree:
            source_index = self.proxy_model.mapToSource(index)
            path = self.model.filePath(source_index)
        elif tree == self.playlist_tree:
            source_index = self.playlist_proxy_model.mapToSource(index)
            path = self.playlist_model.filePath(source_index)
        else:
            return

        if os.path.isfile(path):
            if path.lower().endswith(".pls"):
                self._add_paths_from_pls(path)
            elif path.lower().endswith(tuple(self.image_extensions)):
                base_name = os.path.splitext(os.path.basename(path))[0]
                item_text = f"⭐ {base_name}" if path in self.favorites else base_name
                item = QListWidgetItem(f"🎼 {item_text}")
                item.setData(Qt.UserRole, path)
                self.list_widget.addItem(item)
        elif os.path.isdir(path):
            tree.setExpanded(index, not tree.isExpanded(index))


    def handle_list_double_click(self, item):
        self.list_widget.takeItem(self.list_widget.row(item))

    def show_list_widget_context_menu(self, pos):
        """리스트 위젯에서 마우스 우클릭 시 컨텍스트 메뉴를 표시합니다."""
        item = self.list_widget.itemAt(pos)
        if not item:
            return

        menu = QMenu()

        action_start_show_current = QAction("현재 곡부터 쇼 시작", self)
        action_start_show_current.triggered.connect(self.start_show_from_current)
        menu.addAction(action_start_show_current)
        menu.addSeparator()

        action_delete = QAction("삭제", self)
        action_delete.triggered.connect(self.delete_selected_items)
        menu.addAction(action_delete)

        if len(self.list_widget.selectedItems()) == 1:
            menu.addSeparator()
            action_move_top = QAction("맨 위로 이동", self)
            action_move_top.triggered.connect(self.move_item_top)
            menu.addAction(action_move_top)
            action_move_up = QAction("위로 이동", self)
            action_move_up.triggered.connect(self.move_item_up)
            menu.addAction(action_move_up)
            action_move_down = QAction("아래로 이동", self)
            action_move_down.triggered.connect(self.move_item_down)
            menu.addAction(action_move_down)
            action_move_bottom = QAction("맨 아래로 이동", self)
            action_move_bottom.triggered.connect(self.move_item_bottom)
            menu.addAction(action_move_bottom)

        menu.exec(self.list_widget.mapToGlobal(pos))

    def delete_selected_items(self):
        for item in self.list_widget.selectedItems():
            self.list_widget.takeItem(self.list_widget.row(item))

    def delete_all_items(self):
        reply = QMessageBox.question(
            self, '전체 삭제 확인', '정말로 모든 찬양 목록을 삭제하시겠습니까?',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.list_widget.clear()

    def move_item_up(self):
        row = self.list_widget.currentRow()
        if row > 0:
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row - 1, item)
            self.list_widget.setCurrentRow(row - 1)

    def move_item_down(self):
        row = self.list_widget.currentRow()
        if row < self.list_widget.count() - 1:
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row + 1, item)
            self.list_widget.setCurrentRow(row + 1)

    def move_item_top(self):
        row = self.list_widget.currentRow()
        if row > 0:
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(0, item)
            self.list_widget.setCurrentRow(0)

    def move_item_bottom(self):
        row = self.list_widget.currentRow()
        if row < self.list_widget.count() - 1:
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(self.list_widget.count(), item)
            self.list_widget.setCurrentRow(self.list_widget.count() - 1)

    def save_list(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "리스트 저장", self.playlist_path, "Praise List Files (*.pls)"
        )
        if path:
            if not path.lower().endswith(".pls"):
                path += ".pls"
            
            items_to_save = [
                os.path.relpath(self.list_widget.item(i).data(Qt.UserRole), self.sheet_music_path) 
                for i in range(self.list_widget.count())
            ]
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(items_to_save, f, indent=4)
                QMessageBox.information(self, "저장 완료", "리스트가 성공적으로 저장되었습니다.")
            except Exception as e:
                QMessageBox.critical(self, "저장 오류", f"리스트를 저장하는 중 오류가 발생했습니다: {e}")

    def load_list(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "리스트 불러오기", self.playlist_path, "Praise List Files (*.pls);;All Files (*)"
        )
        if path:
            self.list_widget.clear()
            self._add_paths_from_pls(path)
            QMessageBox.information(self, "불러오기 완료", "리스트가 성공적으로 불러와졌습니다.")


    def preview_selected_file(self, current_index, tree_view):
        """두 트리 뷰 중 하나에서 항목이 선택될 때 미리보기를 업데이트합니다."""
        if not current_index.isValid() or current_index.column() != 0:
            self.current_preview_path = None
            self.update_preview_panel(None)
            return
            
        if tree_view == self.tree:
            source_index = self.proxy_model.mapToSource(current_index)
            path = self.model.filePath(source_index)
        elif tree_view == self.playlist_tree:
            source_index = self.playlist_proxy_model.mapToSource(current_index)
            path = self.playlist_model.filePath(source_index)
        else:
            return
        
        self.current_preview_path = path
        self.update_preview_panel(path)

    def update_preview_panel(self, path):
        """파일 형식에 따라 미리보기 패널의 내용을 업데이트합니다."""
        if not path:
            self.preview_label.setText("파일을 선택하여 미리보세요.")
            self.preview_label.setAlignment(Qt.AlignCenter)
            self.preview_stack.setCurrentWidget(self.preview_scroll_area)
            return

        if os.path.isfile(path) and path.lower().endswith(tuple(self.image_extensions)):
            self.preview_stack.setCurrentWidget(self.preview_scroll_area)
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                preview_width = self.preview_scroll_area.viewport().width()
                if preview_width > 0:
                    scaled_pixmap = pixmap.scaledToWidth(int(preview_width * 0.95), Qt.SmoothTransformation)
                    self.preview_label.setPixmap(scaled_pixmap)
                    self.preview_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
                    self.preview_scroll_area.verticalScrollBar().setValue(0)
                else:
                    self.preview_label.setText("미리보기 영역이 너무 작습니다.")
                    self.preview_label.setAlignment(Qt.AlignCenter)
            else:
                self.preview_label.setText("이미지를 불러올 수 없습니다.")
                self.preview_label.setAlignment(Qt.AlignCenter)

        elif os.path.isfile(path) and path.lower().endswith(".pls"):
            self.preview_stack.setCurrentWidget(self.preview_list_widget)
            self.preview_list_widget.clear()
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    relative_paths = json.load(f)
                
                if not relative_paths:
                    item = QListWidgetItem("비어 있는 플레이리스트입니다.")
                    item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                    self.preview_list_widget.addItem(item)
                    return

                for rel_p in relative_paths:
                    p = os.path.normpath(os.path.join(self.sheet_music_path, rel_p))
                    base_name = os.path.splitext(os.path.basename(p))[0]
                    if os.path.exists(p) and os.path.isfile(p):
                        item = QListWidgetItem(f"🎼 {base_name}")
                        item.setData(Qt.UserRole, p)
                        self.preview_list_widget.addItem(item)
                    else:
                        item = QListWidgetItem(f"❌ {base_name} (파일 없음)")
                        item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                        self.preview_list_widget.addItem(item)
            except Exception as e:
                self.preview_stack.setCurrentWidget(self.preview_scroll_area)
                self.preview_label.setText(f"플레이리스트 파일을 읽는 중 오류 발생:\n{e}")
                self.preview_label.setAlignment(Qt.AlignCenter)
        else:
            self.preview_stack.setCurrentWidget(self.preview_scroll_area)
            self.preview_label.setText("선택된 파일은 이미지 또는 .pls 파일이 아닙니다.")
            self.preview_label.setAlignment(Qt.AlignCenter)

    def start_show(self):
        """쇼를 처음부터 시작합니다."""
        paths = [
            self.list_widget.item(i).data(Qt.UserRole) for i in range(self.list_widget.count())
        ]
        if not paths:
            QMessageBox.warning(self, "오류", "표시할 이미지가 없습니다.")
            return
        
        self.viewer = FullScreenViewer(
            paths, self.initial_zoom_percentage, start_index=0,
            scroll_sensitivity=self.scroll_sensitivity # --- [인자 추가] ---
        )
        self.viewer.showFullScreen()

    def start_show_from_current(self):
        """'선택된 찬양' 리스트의 현재 선택된 곡부터 쇼를 시작합니다."""
        paths = [
            self.list_widget.item(i).data(Qt.UserRole) for i in range(self.list_widget.count())
        ]
        if not paths:
            QMessageBox.warning(self, "오류", "표시할 이미지가 없습니다.")
            return
            
        start_index = self.list_widget.currentRow()
        if start_index < 0:
            start_index = 0
            
        self.viewer = FullScreenViewer(
            paths, self.initial_zoom_percentage, start_index=start_index,
            scroll_sensitivity=self.scroll_sensitivity # --- [인자 추가] ---
        )
        self.viewer.showFullScreen()


class FullScreenViewer(QWidget):
    def __init__(self, image_paths, initial_zoom_percentage=80, start_index=0, scroll_sensitivity=30): # --- [인자 추가] ---
        super().__init__()
        self.image_paths = image_paths
        self.current_index = start_index
        if not (0 <= self.current_index < len(self.image_paths)):
            self.current_index = 0
            
        self.initial_zoom = initial_zoom_percentage / 100.0
        self.zoom = self.initial_zoom
        self.scroll_step = scroll_sensitivity # --- [기존 '30'에서 변경] ---
        self.show_ended = False

        self.setWindowTitle("악보 쇼")
        self.setFocusPolicy(Qt.StrongFocus)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFocusPolicy(Qt.NoFocus)
        self.scroll_area.setWidget(self.image_label)
        
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        palette = self.scroll_area.palette()
        palette.setColor(QPalette.Window, QColor("white"))
        self.scroll_area.setPalette(palette)
        self.scroll_area.setAutoFillBackground(True)

        self.end_screen_widget = QWidget()
        end_layout = QVBoxLayout(self.end_screen_widget)
        end_layout.addStretch()
        end_message_label = QLabel("악보 쇼가 끝났습니다. 끝내려면 마우스를 클릭하거나 우측 방향키를 누르세요")
        end_font = QFont("맑은 고딕", 16)
        end_message_label.setFont(end_font)
        end_message_label.setAlignment(Qt.AlignCenter)
        end_message_label.setStyleSheet("color: white;")
        end_layout.addWidget(end_message_label)
        self.end_screen_widget.setStyleSheet("background-color: black;")
        
        self.main_layout = QStackedLayout()
        self.main_layout.addWidget(self.scroll_area)
        self.main_layout.addWidget(self.end_screen_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.main_layout)
        
        # 휠 이벤트를 가로채기 위해 이벤트 필터 설치
        self.scroll_area.viewport().installEventFilter(self)
        
        # --- [수정] 다음 곡 정보 라벨 추가 ---
        self.next_song_label = QLabel(self)
        self.next_song_label.setStyleSheet(
            "background-color: rgba(0, 0, 0, 30);"
            "color: white;"
            "font-size: 14pt;"
            "padding: 5px;"
            "border-radius: 3px;"
        )
        self.next_song_label.hide()
        # --- [수정] 끝 ---

    def load_image(self):
        if not self.image_paths:
            self.image_label.clear()
            return

        self.zoom = self.initial_zoom
        path = self.image_paths[self.current_index]
        pixmap = QPixmap(path)
        if pixmap.isNull():
            QMessageBox.warning(self, "오류", f"이미지를 불러올 수 없습니다: {path}")
            self.image_label.clear()
            return

        viewer_width = self.scroll_area.viewport().width()
        scaled = pixmap.scaledToWidth(int(viewer_width * self.zoom), Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled)
        
        self.update_next_song_label() # --- [수정] 추가

    def load_image_with_current_zoom(self):
        if not self.image_paths:
            self.image_label.clear()
            return

        path = self.image_paths[self.current_index]
        pixmap = QPixmap(path)
        if pixmap.isNull():
            QMessageBox.warning(self, "오류", f"이미지를 불러올 수 없습니다: {path}")
            self.image_label.clear()
            return

        viewer_width = self.scroll_area.viewport().width()
        scaled = pixmap.scaledToWidth(int(viewer_width * self.zoom), Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled)
        
        self.update_next_song_label() # --- [수정] 추가

    def fit_to_height(self):
        """현재 이미지를 뷰포트의 세로 높이에 맞게 조절합니다."""
        if not self.image_paths:
            return

        path = self.image_paths[self.current_index]
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return

        viewer_height = self.scroll_area.viewport().height()
        scaled = pixmap.scaledToHeight(viewer_height, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled)
        self.scroll_area.verticalScrollBar().setValue(0)
        self.scroll_area.horizontalScrollBar().setValue(0)
        
        self.update_next_song_label() # --- [수정] 추가

    def showEvent(self, event):
        super().showEvent(event)
        self.load_image()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.load_image()
        # load_image()가 update_next_song_label()을 호출하므로
        # 여기서 또 호출할 필요 없이 위치가 자동으로 갱신됩니다.

    def show_first_alert(self):
        QMessageBox.information(self, "알림", "첫 악보입니다")

    def show_end_screen(self):
        self.show_ended = True
        self.main_layout.setCurrentWidget(self.end_screen_widget)
        self.next_song_label.hide() # --- [수정] 추가

    def return_to_last_slide(self):
        """Switches from the end screen back to the last image."""
        self.show_ended = False
        self.main_layout.setCurrentWidget(self.scroll_area)
        self.update_next_song_label() # --- [수정] 추가

    # --- [수정] 다음 곡 라벨 업데이트 메서드 (신규 추가) ---
    def update_next_song_label(self):
        """다음 곡 정보를 가져와 우측 상단에 표시합니다."""
        next_index = self.current_index + 1
        if 0 <= next_index < len(self.image_paths):
            path = self.image_paths[next_index]
            base_name = os.path.splitext(os.path.basename(path))[0]
            
            self.next_song_label.setText(f"NEXT: {base_name}")
            self.next_song_label.adjustSize() # 텍스트 크기에 맞게 라벨 크기 조절
            
            # 우측 상단에 배치 (여백 10px)
            margin = 10
            x = self.width() - self.next_song_label.width() - margin
            y = margin
            self.next_song_label.move(x, y)
            
            self.next_song_label.show()
            self.next_song_label.raise_() # 다른 위젯 위로 올림
        else:
            # 다음 곡이 없음 (마지막 곡임)
            self.next_song_label.hide()
    # --- [수정] 끝 ---

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
            return

        if self.show_ended:
            if event.key() in (Qt.Key_PageDown, Qt.Key_Right):
                self.close()
            elif event.key() in (Qt.Key_PageUp, Qt.Key_Left):
                self.return_to_last_slide()
            return

        if event.key() in (Qt.Key_PageDown, Qt.Key_Right):
            if self.current_index < len(self.image_paths) - 1:
                self.current_index += 1
                self.load_image()
                self.scroll_area.verticalScrollBar().setValue(0)
                self.scroll_area.horizontalScrollBar().setValue(0)
            else:
                self.show_end_screen()
        elif event.key() in (Qt.Key_PageUp, Qt.Key_Left):
            if self.current_index > 0:
                self.current_index -= 1
                self.load_image()
                self.scroll_area.verticalScrollBar().setValue(0)
                self.scroll_area.horizontalScrollBar().setValue(0)
            else:
                self.show_first_alert()
        elif event.key() == Qt.Key_Down:
            v_scroll_bar = self.scroll_area.verticalScrollBar()
            new_value = v_scroll_bar.value() + self.scroll_step
            v_scroll_bar.setValue(min(v_scroll_bar.maximum(), new_value))
        elif event.key() == Qt.Key_Up:
            v_scroll_bar = self.scroll_area.verticalScrollBar()
            new_value = v_scroll_bar.value() - self.scroll_step
            v_scroll_bar.setValue(max(v_scroll_bar.minimum(), new_value))
        elif event.modifiers() == Qt.ControlModifier:
            if event.key() == Qt.Key_Plus:
                self.zoom = min(2.0, self.zoom + 0.1)
                self.load_image_with_current_zoom()
            elif event.key() == Qt.Key_Minus:
                self.zoom = max(0.1, self.zoom - 0.1)
                self.load_image_with_current_zoom()
        elif event.key() == Qt.Key_Plus:
            self.zoom = min(2.0, self.zoom + 0.1)
            self.load_image_with_current_zoom()
        elif event.key() == Qt.Key_Minus:
            self.zoom = max(0.1, self.zoom - 0.1)
            self.load_image_with_current_zoom()
        elif event.key() == Qt.Key_Asterisk:
            self.zoom = 1.0
            self.load_image_with_current_zoom()
        elif event.key() == Qt.Key_0:
            self.fit_to_height()

    def mousePressEvent(self, event):
        if self.show_ended:
            if event.button() == Qt.LeftButton:
                self.close()
            elif event.button() == Qt.RightButton:
                self.return_to_last_slide()
            return

        if event.button() == Qt.LeftButton:
            if self.current_index < len(self.image_paths) - 1:
                self.current_index += 1
                self.load_image()
                self.scroll_area.verticalScrollBar().setValue(0)
                self.scroll_area.horizontalScrollBar().setValue(0)
            else:
                self.show_end_screen()
        elif event.button() == Qt.RightButton:
            if self.current_index > 0:
                self.current_index -= 1
                self.load_image()
                self.scroll_area.verticalScrollBar().setValue(0)
                self.scroll_area.horizontalScrollBar().setValue(0)
            else:
                self.show_first_alert()

    def eventFilter(self, obj, event):
        if obj == self.scroll_area.viewport() and event.type() == QEvent.Wheel:
            if self.show_ended:
                return True # 쇼 종료 화면에서는 휠 무시

            if event.modifiers() == Qt.ControlModifier:
                # Ctrl + 휠: 줌
                if event.angleDelta().y() > 0:
                    self.zoom = min(2.0, self.zoom + 0.1)
                else:
                    self.zoom = max(0.1, self.zoom - 0.1)
                self.load_image_with_current_zoom()
                return True # 이벤트를 처리했음을 알림
            else:
                # 일반 휠: 설정된 값(self.scroll_step)만큼 스크롤
                v_scroll_bar = self.scroll_area.verticalScrollBar()
                scroll_amount = self.scroll_step # --- [기존 '30'에서 변경] ---
                
                if event.angleDelta().y() > 0:
                    # 휠 위로
                    new_value = v_scroll_bar.value() - scroll_amount
                    v_scroll_bar.setValue(max(v_scroll_bar.minimum(), new_value))
                else:
                    # 휠 아래로
                    new_value = v_scroll_bar.value() + scroll_amount
                    v_scroll_bar.setValue(min(v_scroll_bar.maximum(), new_value))
                return True # 이벤트를 처리했음을 알림
        
        # 다른 위젯이나 다른 이벤트는 기본 핸들러로 전달
        return super().eventFilter(obj, event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = PraiseSheetViewer()
    
    viewer.showMaximized()
    
    sys.exit(app.exec())