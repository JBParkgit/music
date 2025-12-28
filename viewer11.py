import sys
import json
import os
import re
import sqlite3
import webbrowser
import urllib.parse
import subprocess

from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QFileSystemModel,
    QTreeView,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QFileDialog,
    QListWidgetItem,
    QScrollArea,
    QLabel,
    QMessageBox,
    QMenu,
    QToolTip,
    QLineEdit,
    QSizePolicy,
    QSlider,
    QAbstractItemView,
    QComboBox,
    QStyle,
    QStackedLayout,
    QGroupBox,
    QSplitter,
    QDialog,
    QTextEdit,
    QDialogButtonBox,
    QTabWidget,
    QFormLayout,
    QCheckBox,
    QInputDialog,
    QProgressBar,
    QPlainTextEdit,
    QGraphicsOpacityEffect,
)
from PySide6.QtGui import (
    QPixmap,
    QPalette,
    QColor,
    QAction,
    QFont,
    QIcon,
    QKeySequence,
    QScreen,
    QPainter,
    QBrush,
    QPen,
)
from PySide6.QtCore import (
    Qt,
    QPoint,
    QDir,
    QModelIndex,
    QRegularExpression,
    QSortFilterProxyModel,
    Signal,
    QEvent,
    QTimer,
    QPropertyAnimation,
    QEasingCurve,
    Property,
    QRect,
    QThread,
)

# --- 구글 드라이브 연동 라이브러리 ---
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload

    GOOGLE_LIB_AVAILABLE = True
except ImportError:
    GOOGLE_LIB_AVAILABLE = False
    print("Google API 라이브러리가 설치되지 않았습니다.")


# --- [기존 클래스 유지] ---
class CustomSortFilterProxyModel(QSortFilterProxyModel):
    itemRenamed = Signal(str)

    def __init__(self, extensions, favorites, metadata_cache, parent=None):
        super().__init__(parent)
        self.extensions = extensions
        self.favorites = favorites
        self.metadata_cache = metadata_cache
        self.lyrics_filter_set = None
        self.favorites_only_mode = False
        self.key_filter = "전체"
        self._filter_regex = QRegularExpression("")
        self.setRecursiveFilteringEnabled(False)
        self.setSortRole(Qt.DisplayRole)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return super().data(index, role)

        source_index = self.mapToSource(index)
        source_model = self.sourceModel()

        if role == Qt.UserRole:
            file_path = source_model.filePath(source_index)
            if file_path in self.metadata_cache:
                song_key = self.metadata_cache[file_path][0]
                return song_key if song_key else ""
            return ""

        if role == Qt.DisplayRole:
            file_name = source_model.fileName(source_index)
            if not source_model.isDir(source_index):
                file_path = source_model.filePath(source_index)
                if file_path in self.favorites:
                    return f"⭐ {file_name}"
                else:
                    return file_name
            return file_name

        if role == Qt.EditRole:
            file_name = source_model.fileName(source_index)
            if not source_model.isDir(source_index):
                return os.path.splitext(file_name)[0]
            else:
                return file_name

        return super().data(index, role)

    def set_lyrics_filter(self, paths_set):
        self.lyrics_filter_set = paths_set
        if paths_set is not None:
            self.setFilterRegularExpression(QRegularExpression(""))
        self.invalidateFilter()

    def set_key_filter(self, key_text):
        self.key_filter = key_text
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        source_model = self.sourceModel()
        index = source_model.index(source_row, 0, source_parent)
        is_dir = source_model.isDir(index)
        file_path = source_model.filePath(index)

        if self.lyrics_filter_set is not None:
            if is_dir:
                return True
            else:
                return file_path in self.lyrics_filter_set

        if self.favorites_only_mode:
            if is_dir:
                return True
            else:
                return file_path in self.favorites

        if is_dir:
            return True
        else:
            passes_key_check = False
            if self.key_filter == "전체":
                passes_key_check = True
            else:
                metadata = self.metadata_cache.get(file_path, ("", ""))
                song_key = metadata[0]

                if song_key is None:
                    song_key = ""

                if self.key_filter == "미지정":
                    passes_key_check = song_key == ""
                else:
                    passes_key_check = song_key.upper() == self.key_filter.upper()

            if not passes_key_check:
                return False

            file_name = source_model.fileName(index)
            base_name, _ = os.path.splitext(file_name)

            if self._filter_regex.pattern() == "":
                return file_path.lower().endswith(tuple(self.extensions))

            name_matches = self._filter_regex.match(base_name).hasMatch()
            return name_matches and file_path.lower().endswith(tuple(self.extensions))

    def flags(self, index):
        default_flags = super().flags(index)
        if index.isValid():
            return default_flags | Qt.ItemIsEditable
        return default_flags

    def setData(self, index, value, role=Qt.EditRole):
        if role == Qt.EditRole and index.isValid():
            source_index = self.mapToSource(index)
            old_path = self.sourceModel().filePath(source_index)

            if not os.path.isfile(old_path):
                return False

            _, ext = os.path.splitext(old_path)
            new_name = f"{value}{ext}"

            dir_path = os.path.dirname(old_path)
            new_path = os.path.join(dir_path, new_name)

            if old_path == new_path:
                return True

            if os.path.exists(new_path):
                QMessageBox.warning(
                    None,
                    "이름 바꾸기 오류",
                    f"같은 이름의 파일이 이미 존재합니다: {new_name}",
                )
                return False

            try:
                os.rename(old_path, new_path)
                if old_path in self.favorites:
                    self.favorites.remove(old_path)
                    self.favorites.add(new_path)
                    if self.parent():
                        self.parent().save_favorites()

                if old_path in self.metadata_cache:
                    key, lyrics = self.metadata_cache.pop(old_path)
                    self.metadata_cache[new_path] = (key, lyrics)
                    if self.parent():
                        parent_window = self.parent()
                        parent_window.set_metadata_in_db(new_path, key, lyrics)
                        try:
                            con = sqlite3.connect(parent_window.db_path)
                            cur = con.cursor()
                            cur.execute(
                                "DELETE FROM song_metadata WHERE file_path = ?",
                                (old_path,),
                            )
                            con.commit()
                            con.close()
                        except Exception as e:
                            print(f"DB 이전 경로 삭제 오류: {e}")

                self.itemRenamed.emit(new_path)
                return True
            except OSError as e:
                QMessageBox.warning(
                    None, "이름 바꾸기 오류", f"파일 이름을 변경할 수 없습니다: {e}"
                )
                return False

        return super().setData(index, value, role)

    def setFilterRegularExpression(self, pattern: QRegularExpression):
        self._filter_regex = pattern
        self.invalidateFilter()

    def set_favorites_only_mode(self, enabled):
        self.favorites_only_mode = enabled
        self.invalidateFilter()


# --- [구글 드라이브 헬퍼 클래스] ---
class GoogleDriveSync:
    def __init__(self, service_account_file, local_dir, drive_folder_id, app_dir):
        self.SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
        self.service_account_file = service_account_file
        self.local_dir = local_dir
        self.drive_folder_id = drive_folder_id
        self.app_dir = app_dir
        self.service = None

    def connect(self):
        if not GOOGLE_LIB_AVAILABLE:
            return False
        try:
            creds = service_account.Credentials.from_service_account_file(
                self.service_account_file, scopes=self.SCOPES
            )
            self.service = build("drive", "v3", credentials=creds)
            return True
        except Exception as e:
            print(f"연결 실패: {e}")
            return False

    def _download_file(self, file_id, file_path):
        request = self.service.files().get_media(fileId=file_id)
        with open(file_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()


# --- [동기화 진행 상황 다이얼로그] ---
class SyncProgressDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("온라인 악보 동기화")
        self.setFixedSize(500, 400)
        self.setModal(True)

        layout = QVBoxLayout(self)

        self.status_label = QLabel("서버에 연결 중입니다...")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)

        self.btn_close = QPushButton("닫기")
        self.btn_close.clicked.connect(self.accept)
        self.btn_close.setEnabled(False)
        layout.addWidget(self.btn_close)

    def append_log(self, message):
        self.log_view.appendPlainText(message)
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum()
        )

    def update_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.status_label.setText(f"진행 중: {current}/{total}")

    def finish_sync(self, success, msg):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.status_label.setText(msg)
        self.btn_close.setEnabled(True)
        self.btn_close.setText("완료 및 닫기")


# --- [백그라운드 동기화 스레드] ---
class SyncThread(QThread):
    progress_signal = Signal(int, int)
    log_signal = Signal(str)
    finished_signal = Signal(bool, int, bool, str)

    def __init__(self, sync_helper):
        super().__init__()
        self.sync_helper = sync_helper

    def run(self):
        try:
            self.log_signal.emit("Google Drive에 연결 중...")
            if not self.sync_helper.connect():
                self.finished_signal.emit(
                    False, 0, False, "구글 인증 실패: service_account.json 확인"
                )
                return

            self.log_signal.emit(
                "전체 파일 목록을 받아오는 중... (시간이 조금 걸릴 수 있습니다)"
            )
            items = []
            page_token = None
            query = f"'{self.sync_helper.drive_folder_id}' in parents and trashed=false"

            while True:
                results = (
                    self.sync_helper.service.files()
                    .list(
                        q=query,
                        pageSize=1000,
                        fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
                        pageToken=page_token,
                    )
                    .execute()
                )

                fetched_items = results.get("files", [])
                items.extend(fetched_items)

                page_token = results.get("nextPageToken")
                if not page_token:
                    break

                self.log_signal.emit(
                    f"파일 목록 읽는 중... (현재 {len(items)}개 확인됨)"
                )

            download_list = []
            db_file = None
            self.log_signal.emit(
                f"총 {len(items)}개의 파일 검색됨. 동기화 대상 확인 중..."
            )

            for item in items:
                if "application/vnd.google-apps" in item["mimeType"]:
                    continue

                file_name = item["name"]
                if file_name == "song_metadata.db":
                    db_file = item
                    continue

                local_path = os.path.join(self.sync_helper.local_dir, file_name)
                if not os.path.exists(local_path):
                    download_list.append(item)

            total_actions = len(download_list) + (1 if db_file else 0)
            current_action = 0
            download_count = 0
            db_updated = False

            for item in download_list:
                current_action += 1
                file_name = item["name"]
                local_path = os.path.join(self.sync_helper.local_dir, file_name)

                self.log_signal.emit(f"[다운로드] {file_name}")
                self.progress_signal.emit(current_action, total_actions)

                try:
                    self.sync_helper._download_file(item["id"], local_path)
                    download_count += 1
                except Exception as e:
                    self.log_signal.emit(f"❌ 실패: {file_name} - {e}")

            if db_file:
                current_action += 1
                self.log_signal.emit("[업데이트] 곡 정보 DB (song_metadata.db)")
                self.progress_signal.emit(current_action, total_actions)
                local_db_path = os.path.join(
                    self.sync_helper.app_dir, "song_metadata.db"
                )
                try:
                    self.sync_helper._download_file(db_file["id"], local_db_path)
                    db_updated = True
                except Exception as e:
                    self.log_signal.emit(f"❌ DB 다운로드 실패 - {e}")

            final_msg = "동기화가 완료되었습니다."
            if download_count == 0 and not db_updated:
                final_msg = f"총 {len(items)}개 파일 확인됨. (새로운 파일 없음)"

            self.finished_signal.emit(True, download_count, db_updated, final_msg)

        except Exception as e:
            self.finished_signal.emit(False, 0, False, f"오류 발생: {str(e)}")


# --- [메인 윈도우 클래스] ---
class PraiseSheetViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("물댄동산 악보 뷰어 Pet1 2:9 V3")  # 버전 업

        # --- [최적화] 폰트 워밍업 ---
        self.font_warmer = QLabel("⭐ 🎼", self)
        self.font_warmer.setGeometry(-100, -100, 10, 10)
        self.font_warmer.show()

        self.viewer = None  # 쇼창 인스턴스
        self.current_tooltip_index = QModelIndex()
        self.current_playlist_tooltip_item = None
        self.current_preview_path = None
        self.inspector_current_path = None
        self.sync_thread = None

        # --- 경로 및 DB 설정 ---
        if getattr(sys, "frozen", False):
            self.app_dir = os.path.dirname(sys.executable)
        else:
            self.app_dir = os.path.dirname(os.path.abspath(__file__))

        self.db_path = os.path.join(self.app_dir, "song_metadata.db")
        self.init_database()
        self.metadata_cache = self.load_all_metadata_from_db()

        # --- 아이콘 및 설정 로드 ---
        try:
            window_icon_path = os.path.join(self.app_dir, "musicsheet.ico")
            if os.path.exists(window_icon_path):
                self.setWindowIcon(QIcon(window_icon_path))
        except Exception:
            pass

        self.settings_file = os.path.join(self.app_dir, "settings.json")
        self.themes = self.get_themes()
        self.load_settings()

        self.favorites = set()
        self.favorites_file = os.path.join(self.app_dir, "favorites.json")
        self.load_favorites()
        self.favorites_view_active = False

        # --- 파일 시스템 모델 ---
        self.image_extensions = [".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"]
        self.all_extensions = self.image_extensions + [".pls"]

        self.model = QFileSystemModel()
        self.model.setRootPath(self.sheet_music_path)
        self.model.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot | QDir.Files)

        self.proxy_model = CustomSortFilterProxyModel(
            self.all_extensions, self.favorites, self.metadata_cache, self
        )
        self.proxy_model.setSourceModel(self.model)
        self.proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy_model.itemRenamed.connect(self.update_selection_after_rename)

        self.playlist_model = QFileSystemModel()
        self.playlist_model.setRootPath(self.playlist_path)
        self.playlist_model.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot | QDir.Files)
        self.playlist_proxy_model = CustomSortFilterProxyModel(
            [".pls"], set(), {}, self
        )
        self.playlist_proxy_model.setSourceModel(self.playlist_model)
        self.playlist_proxy_model.itemRenamed.connect(
            self.update_selection_after_rename
        )

        # --- UI 구성 ---
        self.path_label = QLineEdit(os.path.normpath(self.sheet_music_path))
        self.path_label.setReadOnly(True)
        self.btn_change_folder = QPushButton("폴더 변경")
        self.btn_change_folder.setFixedWidth(80)
        self.btn_change_folder.clicked.connect(self.change_sheet_music_folder)

        self.btn_sync_drive = QPushButton("온라인 악보 받기")
        self.btn_sync_drive.setMinimumWidth(150)  # 또는 160~180
        self.btn_sync_drive.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.btn_sync_drive.clicked.connect(self.run_google_sync)
        if not GOOGLE_LIB_AVAILABLE:
            self.btn_sync_drive.setEnabled(False)
            self.btn_sync_drive.setToolTip(
                "Google API 라이브러리가 설치되지 않았습니다."
            )

        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("악보 폴더:"))
        path_layout.addWidget(self.path_label)
        path_layout.addWidget(self.btn_change_folder)
        path_layout.addWidget(self.btn_sync_drive)

        self.playlist_path_label = QLineEdit(os.path.normpath(self.playlist_path))
        self.playlist_path_label.setReadOnly(True)
        self.btn_change_playlist_folder = QPushButton("폴더 변경")
        self.btn_change_playlist_folder.setFixedWidth(88)
        self.btn_change_playlist_folder.clicked.connect(self.change_playlist_folder)
        playlist_path_layout = QHBoxLayout()
        playlist_path_layout.addWidget(QLabel("플레이리스트 폴더:"))
        playlist_path_layout.addWidget(self.playlist_path_label)
        playlist_path_layout.addWidget(self.btn_change_playlist_folder)

        # --- 트리 뷰 ---
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
        self.tree.mouseMoveEvent = lambda event: self.handle_tree_mouse_move(
            event, self.tree
        )
        self.tree.setEditTriggers(QAbstractItemView.EditKeyPressed)

        self.playlist_tree = QTreeView()
        self.playlist_tree.setModel(self.playlist_proxy_model)
        self.playlist_tree.setRootIndex(
            self.playlist_proxy_model.mapFromSource(
                self.playlist_model.index(self.playlist_path)
            )
        )
        self.playlist_tree.setColumnHidden(1, True)
        self.playlist_tree.setColumnHidden(2, True)
        self.playlist_tree.setColumnHidden(3, True)
        self.playlist_tree.setSelectionMode(QTreeView.SingleSelection)
        self.playlist_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.playlist_tree.customContextMenuRequested.connect(
            self.show_playlist_context_menu
        )
        self.playlist_tree.doubleClicked.connect(self.handle_tree_double_click)
        self.playlist_tree.setMouseTracking(True)
        self.playlist_tree.mouseMoveEvent = lambda event: self.handle_tree_mouse_move(
            event, self.playlist_tree
        )
        self.playlist_tree.setEditTriggers(QAbstractItemView.EditKeyPressed)

        # --- 검색 UI ---
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300)
        self.search_timer.timeout.connect(self.perform_search_filter)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("악보 검색...")
        self.search_input.textChanged.connect(self.on_search_text_changed)

        self.search_type_combo = QComboBox()
        self.search_type_combo.addItems(["파일이름", "가사"])
        self.search_type_combo.setFixedWidth(95)

        self.btn_reset_search = QPushButton("초기화")
        self.btn_reset_search.setFixedWidth(80)
        self.btn_reset_search.clicked.connect(self.reset_search_filter)

        search_layout = QHBoxLayout()
        search_layout.addWidget(self.search_type_combo)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.btn_reset_search)

        self.btn_launch_capture = QPushButton("📸 악보 수집 도구 실행")
        self.btn_launch_capture.clicked.connect(self.launch_capture_tool)

        self.sheet_sort_combo = QComboBox()
        self.sheet_sort_combo.addItems(
            [
                "이름순 (오름차순)",
                "이름순 (내림차순)",
                "키(Key)순 (오름차순)",
                "키(Key)순 (내림차순)",
            ]
        )
        self.sheet_sort_combo.currentTextChanged.connect(self.change_sheet_sort_order)

        self.key_filter_combo = QComboBox()
        self.key_filter_combo.addItems(
            [
                "전체",
                "A",
                "A#",
                "B",
                "C",
                "C#",
                "D",
                "D#",
                "E",
                "F",
                "F#",
                "G",
                "G#",
                "미지정",
            ]
        )
        self.key_filter_combo.currentTextChanged.connect(self.on_key_filter_changed)

        sheet_controls_layout = QHBoxLayout()
        sheet_controls_layout.addWidget(QLabel("정렬:"))
        sheet_controls_layout.addWidget(self.sheet_sort_combo)
        sheet_controls_layout.addWidget(QLabel("Key 필터:"))
        sheet_controls_layout.addWidget(self.key_filter_combo)

        self.playlist_search_timer = QTimer(self)
        self.playlist_search_timer.setSingleShot(True)
        self.playlist_search_timer.setInterval(300)
        self.playlist_search_timer.timeout.connect(self.perform_playlist_search_filter)

        self.playlist_search_input = QLineEdit()
        self.playlist_search_input.setPlaceholderText("플레이리스트 검색...")
        self.playlist_search_input.textChanged.connect(self.playlist_search_timer.start)
        self.btn_reset_playlist_search = QPushButton("초기화")
        self.btn_reset_playlist_search.setFixedWidth(80)
        self.btn_reset_playlist_search.clicked.connect(
            self.reset_playlist_search_filter
        )
        playlist_search_layout = QHBoxLayout()
        playlist_search_layout.addWidget(self.playlist_search_input)
        playlist_search_layout.addWidget(self.btn_reset_playlist_search)

        self.playlist_sort_combo = QComboBox()
        self.playlist_sort_combo.addItems(
            [
                "수정날짜순 (최신)",
                "수정날짜순 (오래된)",
                "이름순 (오름차순)",
                "이름순 (내림차순)",
            ]
        )
        self.playlist_sort_combo.setCurrentText("수정날짜순 (최신)")
        self.playlist_sort_combo.currentTextChanged.connect(
            self.change_playlist_sort_order
        )
        playlist_sort_layout = QHBoxLayout()
        playlist_sort_layout.addWidget(QLabel("정렬:"))
        playlist_sort_layout.addWidget(self.playlist_sort_combo)

        title_font = QFont("맑은 고딕", 14, QFont.Bold)
        self.tree_title = QLabel("악보 선택")
        self.tree_title.setObjectName("panelTitle")
        self.tree_title.setFont(title_font)
        self.tree_title.setAlignment(Qt.AlignCenter)
        self.preview_title = QLabel("악보 미리보기")
        self.preview_title.setObjectName("panelTitle")
        self.preview_title.setFont(title_font)
        self.preview_title.setAlignment(Qt.AlignCenter)
        self.list_title = QLabel("선택된 찬양 리스트")
        self.list_title.setObjectName("panelTitle")
        self.list_title.setFont(title_font)
        self.list_title.setAlignment(Qt.AlignCenter)

        # --- 중앙 패널 ---
        self.preview_label = QLabel("파일을 선택하여 미리보세요.")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setFont(QFont("맑은 고딕", 12))
        self.preview_scroll_area = QScrollArea()
        self.preview_scroll_area.setWidgetResizable(True)
        self.preview_scroll_area.setWidget(self.preview_label)

        self.preview_list_widget = QListWidget()
        self.preview_list_widget.itemDoubleClicked.connect(
            self.add_preview_list_item_to_main_list
        )
        self.preview_list_widget.setMouseTracking(True)
        self.preview_list_widget.mouseMoveEvent = self.playlist_preview_mouse_move_event

        self.preview_container = QWidget()
        self.preview_stack = QStackedLayout(self.preview_container)
        self.preview_stack.addWidget(self.preview_scroll_area)
        self.preview_stack.addWidget(self.preview_list_widget)

        self.btn_show_single = QPushButton("이 곡 쇼하기 (F6)")
        self.btn_show_single.setShortcut(Qt.Key_F6)
        self.btn_show_single.clicked.connect(self.start_single_song_show)

        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.addWidget(self.preview_title)
        preview_layout.addWidget(self.preview_container)
        preview_layout.addWidget(self.btn_show_single)

        inspector_group_box = QGroupBox("곡 정보")
        inspector_layout = QFormLayout(inspector_group_box)

        self.inspector_key_combo = QComboBox()
        self.inspector_key_combo.addItems(
            ["", "A", "A#", "B", "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#"]
        )

        self.inspector_lyrics_edit = QTextEdit()
        self.inspector_lyrics_edit.setAcceptRichText(False)
        self.inspector_lyrics_edit.setPlaceholderText(
            "가사 전체 또는 검색에 사용할 핵심 구절을 입력하세요."
        )

        self.btn_google_lyrics = QPushButton("Google 가사 검색")
        self.btn_google_lyrics.clicked.connect(self.search_lyrics_on_google)

        lyrics_label_layout = QHBoxLayout()
        lyrics_label_layout.addWidget(QLabel("가사:"))
        lyrics_label_layout.addStretch()
        lyrics_label_layout.addWidget(self.btn_google_lyrics)

        inspector_layout.addRow("곡 Key:", self.inspector_key_combo)
        inspector_layout.addRow(lyrics_label_layout)
        inspector_layout.addRow(self.inspector_lyrics_edit)

        self.center_splitter = QSplitter(Qt.Vertical)
        self.center_splitter.addWidget(preview_widget)
        self.center_splitter.addWidget(inspector_group_box)
        self.center_splitter.setSizes([600, 200])

        self.inspector_key_combo.currentTextChanged.connect(
            self.on_inspector_key_changed
        )
        self.inspector_lyrics_edit.installEventFilter(self)
        self.load_metadata_to_inspector(None)

        # --- 즐겨찾기 및 선택 버튼 ---
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

        # --- 메인 좌측 레이아웃 조립 ---
        self.status_bar_label = QLabel()
        splitter = QSplitter(Qt.Vertical)

        top_container = QWidget()
        top_layout = QVBoxLayout(top_container)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addLayout(path_layout)
        top_layout.addLayout(search_layout)
        top_layout.addWidget(self.btn_launch_capture)
        top_layout.addLayout(sheet_controls_layout)
        top_layout.addWidget(self.tree)
        top_layout.addWidget(self.status_bar_label)
        top_layout.addLayout(favorites_button_layout)
        top_layout.addWidget(self.btn_add_selected)

        bottom_container = QWidget()
        bottom_layout = QVBoxLayout(bottom_container)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
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

        # --- [최적화] 리스트 위젯 설정 ---
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        self.list_widget.setDragEnabled(True)
        self.list_widget.setAcceptDrops(True)
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.itemDoubleClicked.connect(self.handle_list_double_click)
        self.list_widget.itemClicked.connect(self.handle_list_click)

        list_font = QFont()
        list_font.setPointSize(12)
        self.list_widget.setFont(list_font)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(
            self.show_list_widget_context_menu
        )

        # --- 우측 패널 버튼 및 설정 ---
        self.btn_delete = QPushButton("선택 삭제")
        self.btn_delete.clicked.connect(self.delete_selected_items)
        self.btn_delete_all = QPushButton("전체 삭제")
        self.btn_delete_all.clicked.connect(self.delete_all_items)

        # [추가] 인터미션 추가 버튼
        self.btn_insert_intermission = QPushButton("☕ 인터미션 추가")
        self.btn_insert_intermission.clicked.connect(self.insert_intermission_item)

        self.show_title_label = QLabel("쇼 시작")
        self.show_title_label.setFont(QFont("맑은 고딕", 14, QFont.Bold))
        self.show_title_label.setAlignment(Qt.AlignCenter)

        self.btn_start_from_first = QPushButton("처음 곡부터 (F5)")
        self.btn_start_from_first.setShortcut(Qt.Key_F5)
        self.btn_start_from_current = QPushButton("현재 곡부터 (Shift+F5)")
        self.btn_start_from_current.setShortcut(QKeySequence("Shift+F5"))
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

        self.scroll_label = QLabel()
        self.scroll_slider = QSlider(Qt.Horizontal)
        self.scroll_slider.setRange(10, 150)
        self.scroll_slider.setValue(self.scroll_sensitivity)
        self.scroll_slider.valueChanged.connect(self.update_scroll_label)
        self.update_scroll_label(self.scroll_sensitivity)
        scroll_layout = QHBoxLayout()
        scroll_layout.addWidget(QLabel("스크롤 민감도:"))
        scroll_layout.addWidget(self.scroll_slider)
        scroll_layout.addWidget(self.scroll_label)

        # --- 로고 이미지 설정 ---
        self.logo_path_label = QLineEdit(self.logo_image_path)
        self.logo_path_label.setReadOnly(True)
        self.logo_path_label.setPlaceholderText("로고 파일 없음")
        self.btn_change_logo = QPushButton("변경")
        self.btn_change_logo.clicked.connect(self.change_logo_image)

        logo_layout = QHBoxLayout()
        logo_layout.addWidget(QLabel("로고:"))
        logo_layout.addWidget(self.logo_path_label)
        logo_layout.addWidget(self.btn_change_logo)

        # --- 쇼 제어 기능 ---
        self.btn_toggle_dual_viewer = QPushButton("쇼창 켜기")
        self.btn_toggle_dual_viewer.setCheckable(True)
        self.btn_toggle_dual_viewer.clicked.connect(self.toggle_dual_monitor_viewer)

        self.btn_black_screen = QPushButton("블랙 스크린 (B)")
        self.btn_black_screen.setShortcut(Qt.Key_B)
        self.btn_black_screen.clicked.connect(self.remote_toggle_black)

        self.btn_logo_screen = QPushButton("로고 화면 (L)")
        self.btn_logo_screen.setShortcut(Qt.Key_L)
        self.btn_logo_screen.clicked.connect(self.remote_toggle_logo)

        screen_control_layout = QHBoxLayout()
        screen_control_layout.addWidget(self.btn_black_screen)
        screen_control_layout.addWidget(self.btn_logo_screen)

        self.monitor_combo = QComboBox()
        self.init_monitor_selection()

        dual_control_layout = QVBoxLayout()
        dual_control_layout.setSpacing(8)

        # 쇼 시작 버튼 (한 줄)
        start_buttons_layout = QHBoxLayout()
        start_buttons_layout.addWidget(self.btn_start_from_first)
        start_buttons_layout.addWidget(self.btn_start_from_current)

        dual_control_layout.addLayout(start_buttons_layout)

        dual_control_layout.addWidget(self.btn_toggle_dual_viewer)
        dual_control_layout.addWidget(self.monitor_combo)
        dual_control_layout.addLayout(screen_control_layout)

        dual_group = QGroupBox("쇼 하기")
        dual_group.setLayout(dual_control_layout)

        # --- 버튼 그룹핑 ---
        button_layout1 = QHBoxLayout()  # 이동
        button_layout1.addWidget(self.btn_move_top)
        button_layout1.addWidget(self.btn_move_up)
        button_layout1.addWidget(self.btn_move_down)
        button_layout1.addWidget(self.btn_move_bottom)

        button_layout2 = QHBoxLayout()  # 파일
        button_layout2.addWidget(self.btn_delete)
        button_layout2.addWidget(self.btn_delete_all)
        button_layout2.addWidget(self.btn_insert_intermission)  # [추가]
        button_layout2.addWidget(self.btn_save_list)
        button_layout2.addWidget(self.btn_load_list)

        shortcut_group_box = QGroupBox("쇼 화면 단축키 안내")
        shortcut_layout = QVBoxLayout(shortcut_group_box)
        shortcut_label = QLabel()
        shortcut_text = """
        <b>- 다음:</b> PgDn, →, 마우스 좌클릭<br>
        <b>- 이전:</b> PgUp, ←, 마우스 우클릭<br>
        <b>- 블랙 / 로고:</b> B / L<br>
        <b>- 확대 / 축소:</b> + / - (Ctrl 가능)<br>
        <b>- 너비 맞춤(가로):</b> *<br>
        <b>- 높이 맞춤(세로):</b> 0<br>
        <b>- 종료/복귀:</b> Esc
        """
        shortcut_label.setText(shortcut_text)
        shortcut_label.setWordWrap(True)
        shortcut_label.setAlignment(Qt.AlignLeft)
        shortcut_layout.addWidget(shortcut_label)

        # --- [디자인 개선] 버튼 역할(ObjectName) 지정 (기능 영향 없음) ---
        # QSS에서 #primary / #secondary / #danger / #ghost 로 스타일 구분
        self.btn_show_single.setObjectName("primary")
        self.btn_start_from_first.setObjectName("primary")
        self.btn_start_from_current.setObjectName("primary")
        self.btn_launch_capture.setObjectName("primary")

        self.btn_change_folder.setObjectName("secondary")
        self.btn_sync_drive.setObjectName("secondary")
        self.btn_change_playlist_folder.setObjectName("secondary")
        self.btn_add_selected.setObjectName("secondary")
        self.btn_add_favorite.setObjectName("secondary")
        self.btn_remove_favorite.setObjectName("secondary")
        self.btn_toggle_favorites_view.setObjectName("secondary")
        self.btn_save_list.setObjectName("secondary")
        self.btn_load_list.setObjectName("secondary")
        self.btn_move_top.setObjectName("secondary")
        self.btn_move_up.setObjectName("secondary")
        self.btn_move_down.setObjectName("secondary")
        self.btn_move_bottom.setObjectName("secondary")
        self.btn_toggle_dual_viewer.setObjectName("secondary")
        self.btn_insert_intermission.setObjectName("secondary")
        self.btn_change_logo.setObjectName("secondary")
        self.btn_reset_search.setObjectName("secondary")
        self.btn_reset_playlist_search.setObjectName("secondary")

        self.btn_black_screen.setObjectName("ghost")
        self.btn_logo_screen.setObjectName("ghost")

        self.btn_delete.setObjectName("danger")
        self.btn_delete_all.setObjectName("danger")

        # --- 우측 레이아웃 배치 순서 ---
        right_layout = QVBoxLayout()
        right_layout.addWidget(self.list_title)
        right_layout.addWidget(self.list_widget, 1)
        right_layout.addLayout(button_layout1)
        right_layout.addLayout(button_layout2)
        right_layout.addWidget(dual_group)
        right_layout.addLayout(theme_layout)
        right_layout.addLayout(zoom_layout)
        right_layout.addLayout(scroll_layout)
        right_layout.addLayout(logo_layout)
        right_layout.addWidget(shortcut_group_box)

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)
        main_layout.addLayout(tree_layout, 2)

        center_layout = QVBoxLayout()
        center_layout.addWidget(self.center_splitter)
        main_layout.addLayout(center_layout, 3)

        main_layout.addLayout(right_layout, 2)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        self.tree.selectionModel().currentChanged.connect(
            lambda current, prev: self.preview_selected_file(current, self.tree)
        )
        self.playlist_tree.selectionModel().currentChanged.connect(
            lambda current, prev: self.preview_selected_file(
                current, self.playlist_tree
            )
        )

        self.model.directoryLoaded.connect(self.update_file_count)
        self.update_file_count(self.sheet_music_path)
        self.change_playlist_sort_order(self.playlist_sort_combo.currentText())

        self.apply_theme(self.current_theme)

        # --- 웜업 ---
        self.warm_up_list_widget()

    # --- [추가] 인터미션 삽입 메서드 ---
    def insert_intermission_item(self):
        """인터미션용 이미지를 선택하여 리스트에 추가합니다."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "인터미션(배경) 이미지 선택",
            self.sheet_music_path,
            "Images (*.jpg *.jpeg *.png *.bmp *.webp)",
        )

        if file_path:
            file_name = os.path.basename(file_path)
            item = QListWidgetItem(f"☕ [Intermission] {file_name}")

            # 데이터 저장: 경로는 UserRole, 인터미션 플래그는 UserRole+1
            item.setData(Qt.UserRole, file_path)
            item.setData(Qt.UserRole + 1, True)

            current_row = self.list_widget.currentRow()
            if current_row >= 0:
                self.list_widget.insertItem(current_row + 1, item)
                self.list_widget.setCurrentRow(current_row + 1)
            else:
                self.list_widget.addItem(item)
                self.list_widget.setCurrentRow(self.list_widget.count() - 1)

    def launch_capture_tool(self):
        exe_name = "sheetcapture.exe"
        exe_path = os.path.join(self.app_dir, exe_name)

        if os.path.exists(exe_path):
            try:
                subprocess.Popen([exe_path])
                self.status_bar_label.setText(f"도구 실행 중: {exe_name}")
            except Exception as e:
                QMessageBox.critical(
                    self, "실행 오류", f"프로그램을 실행할 수 없습니다.\n오류: {e}"
                )
        else:
            QMessageBox.warning(
                self,
                "파일 없음",
                f"'{exe_name}' 파일을 찾을 수 없습니다.\n\n"
                f"뷰어와 같은 폴더에 {exe_name} 파일이 있는지 확인해주세요.\n"
                f"현재 경로: {self.app_dir}",
            )

    def init_monitor_selection(self):
        screens = QApplication.screens()
        self.monitor_combo.clear()

        for i, screen in enumerate(screens):
            size = screen.size()
            self.monitor_combo.addItem(f"모니터 {i+1} ({size.width()}x{size.height()})")

        if len(screens) > 1:
            self.monitor_combo.setCurrentIndex(1)
        else:
            self.monitor_combo.setCurrentIndex(0)

    def warm_up_list_widget(self):
        self.list_widget.setUpdatesEnabled(False)
        dummy_item = QListWidgetItem("🎼 워밍업 ⭐")
        self.list_widget.addItem(dummy_item)
        self.list_widget.setCurrentItem(dummy_item)
        QApplication.processEvents()
        self.list_widget.clear()
        self.list_widget.setUpdatesEnabled(True)

    def eventFilter(self, obj, event):
        if obj == self.inspector_lyrics_edit and event.type() == QEvent.FocusOut:
            self.save_inspector_lyrics()

        if (
            hasattr(self, "viewer")
            and self.viewer
            and obj == self.viewer.scroll_area.viewport()
            and event.type() == QEvent.Wheel
        ):
            return self.viewer.eventFilter(obj, event)

        return super().eventFilter(obj, event)

    def init_database(self):
        try:
            con = sqlite3.connect(self.db_path)
            cur = con.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS song_metadata (
                    file_path TEXT PRIMARY KEY,
                    song_key TEXT,
                    lyrics TEXT
                )
            """
            )
            con.commit()
            con.close()
        except Exception as e:
            QMessageBox.critical(self, "DB 오류", f"데이터베이스 초기화 실패: {e}")

    def get_metadata_from_db(self, file_path):
        try:
            con = sqlite3.connect(self.db_path)
            cur = con.cursor()
            cur.execute(
                "SELECT song_key, lyrics FROM song_metadata WHERE file_path = ?",
                (file_path,),
            )
            result = cur.fetchone()
            con.close()
            if result:
                return result
            return (None, None)
        except Exception as e:
            print(f"DB 읽기 오류: {e}")
            return (None, None)

    def set_metadata_in_db(self, file_path, song_key, lyrics):
        try:
            con = sqlite3.connect(self.db_path)
            cur = con.cursor()
            cur.execute(
                """
                INSERT OR REPLACE INTO song_metadata (file_path, song_key, lyrics)
                VALUES (?, ?, ?)
            """,
                (file_path, song_key, lyrics),
            )
            con.commit()
            con.close()
            self.metadata_cache[file_path] = (song_key, lyrics)
            self.proxy_model.invalidate()
        except Exception as e:
            QMessageBox.critical(self, "DB 오류", f"데이터베이스 저장 실패: {e}")

    def search_lyrics_from_db(self, search_text):
        try:
            con = sqlite3.connect(self.db_path)
            cur = con.cursor()
            keywords = search_text.strip().split()
            if not keywords:
                return set()
            query = "SELECT file_path FROM song_metadata WHERE "
            query += " AND ".join(["lyrics LIKE ?"] * len(keywords))
            params = [f"%{keyword}%" for keyword in keywords]
            cur.execute(query, params)
            results = cur.fetchall()
            con.close()
            return {row[0] for row in results}
        except Exception as e:
            QMessageBox.warning(self, "가사 검색 오류", f"가사 검색 중 오류 발생: {e}")
            return set()

    def load_all_metadata_from_db(self):
        try:
            con = sqlite3.connect(self.db_path)
            cur = con.cursor()
            cur.execute("SELECT file_path, song_key, lyrics FROM song_metadata")
            results = cur.fetchall()
            con.close()
            return {row[0]: (row[1], row[2]) for row in results}
        except Exception as e:
            QMessageBox.critical(self, "DB 오류", f"전체 메타데이터 로드 실패: {e}")
            return {}

    def load_metadata_to_inspector(self, path):
        if (
            path is None
            or not os.path.isfile(path)
            or not path.lower().endswith(tuple(self.image_extensions))
        ):
            self.inspector_current_path = None
            self.inspector_key_combo.blockSignals(True)
            self.inspector_lyrics_edit.blockSignals(True)
            self.inspector_key_combo.setCurrentIndex(0)
            self.inspector_lyrics_edit.clear()
            self.inspector_key_combo.setEnabled(False)
            self.inspector_lyrics_edit.setEnabled(False)
            self.btn_google_lyrics.setEnabled(False)
            self.inspector_key_combo.blockSignals(False)
            self.inspector_lyrics_edit.blockSignals(False)
            return

        self.inspector_current_path = path
        self.inspector_key_combo.setEnabled(True)
        self.inspector_lyrics_edit.setEnabled(True)
        self.btn_google_lyrics.setEnabled(True)

        if path in self.metadata_cache:
            key, lyrics = self.metadata_cache[path]
        else:
            key, lyrics = self.get_metadata_from_db(path)
            if key or lyrics:
                self.metadata_cache[path] = (key, lyrics)

        self.inspector_key_combo.blockSignals(True)
        self.inspector_lyrics_edit.blockSignals(True)
        self.inspector_key_combo.setCurrentText(key if key else "")
        self.inspector_lyrics_edit.setPlainText(lyrics if lyrics else "")
        self.inspector_key_combo.blockSignals(False)
        self.inspector_lyrics_edit.blockSignals(False)

    def on_inspector_key_changed(self, new_key):
        if self.inspector_current_path:
            _key, lyrics = self.get_metadata_from_db(self.inspector_current_path)
            if new_key != _key:
                self.set_metadata_in_db(self.inspector_current_path, new_key, lyrics)

    def save_inspector_lyrics(self):
        if self.inspector_current_path:
            key, old_lyrics = self.get_metadata_from_db(self.inspector_current_path)
            new_lyrics = self.inspector_lyrics_edit.toPlainText()
            if new_lyrics != old_lyrics:
                self.set_metadata_in_db(self.inspector_current_path, key, new_lyrics)

    def search_lyrics_on_google(self):
        if not self.inspector_current_path:
            QMessageBox.warning(self, "알림", "먼저 악보 파일을 선택하세요.")
            return
        base_name = os.path.splitext(os.path.basename(self.inspector_current_path))[0]
        clean_title = re.sub(r"[\(\[].*?[\)\]]", "", base_name).strip()
        if not clean_title:
            clean_title = base_name
        query = f"{clean_title} 가사"
        try:
            safe_query = urllib.parse.quote_plus(query)
            url = f"https://www.google.com/search?q={safe_query}"
            webbrowser.open(url)
        except Exception as e:
            QMessageBox.critical(self, "오류", f"브라우저를 여는 데 실패했습니다: {e}")

    def update_selection_after_rename(self, new_path):
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
        source_index = source_model.index(new_path)
        if source_index.isValid():
            proxy_index = proxy_model.mapFromSource(source_index)
            if proxy_index.isValid():
                tree.setCurrentIndex(proxy_index)

    def playlist_tree_mouse_move_event(self, event):
        index = self.playlist_tree.indexAt(event.position().toPoint())
        if index.isValid() and index != self.current_tooltip_index:
            self.current_tooltip_index = index
            source_index = self.playlist_proxy_model.mapToSource(index)
            path = self.playlist_model.filePath(source_index)
            if os.path.isfile(path) and path.lower().endswith(".pls"):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data_list = json.load(f)
                    # 호환성 체크
                    song_names = []
                    for d in data_list:
                        if isinstance(d, str):
                            song_names.append(os.path.splitext(os.path.basename(d))[0])
                        else:
                            name = os.path.splitext(
                                os.path.basename(d.get("path", ""))
                            )[0]
                            if d.get("is_intermission"):
                                name = f"☕ {name}"
                            song_names.append(name)

                    tooltip_text = "<b>플레이리스트:</b><br>" + "<br>".join(
                        f"- {name}" for name in song_names
                    )
                    QToolTip.showText(
                        event.globalPosition().toPoint() + QPoint(20, 20),
                        tooltip_text,
                        self.playlist_tree,
                    )
                except Exception:
                    QToolTip.showText(
                        event.globalPosition().toPoint() + QPoint(20, 20),
                        "플레이리스트를 읽을 수 없습니다.",
                        self.playlist_tree,
                    )
            else:
                QToolTip.hideText()
        elif not index.isValid():
            QToolTip.hideText()
            self.current_tooltip_index = QModelIndex()
        super(QTreeView, self.playlist_tree).mouseMoveEvent(event)

    def playlist_preview_mouse_move_event(self, event):
        item = self.preview_list_widget.itemAt(event.position().toPoint())
        if item is not None and item != self.current_playlist_tooltip_item:
            self.current_playlist_tooltip_item = item
            path = item.data(Qt.UserRole)
            if (
                path
                and os.path.isfile(path)
                and path.lower().endswith(tuple(self.image_extensions))
            ):
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    fixed_width = 250
                    scaled = pixmap.scaledToWidth(fixed_width, Qt.SmoothTransformation)
                    tooltip = f'<img style="margin:0;padding:0;" src="{path}" width="{scaled.width()}" height="{scaled.height()}"/>'
                    QToolTip.showText(
                        event.globalPosition().toPoint() + QPoint(20, 20),
                        tooltip,
                        self.preview_list_widget,
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
        path = item.data(Qt.UserRole)
        is_intermission = item.data(Qt.UserRole + 1)

        if path and os.path.isfile(path):
            base_name = os.path.splitext(os.path.basename(path))[0]

            if is_intermission:
                display_text = f"☕ [Intermission] {base_name}"
            else:
                item_text = f"⭐ {base_name}" if path in self.favorites else base_name
                display_text = f"🎼 {item_text}"

            new_item = QListWidgetItem(display_text)
            new_item.setData(Qt.UserRole, path)
            if is_intermission:
                new_item.setData(Qt.UserRole + 1, True)

            self.list_widget.addItem(new_item)

    def start_single_song_show(self):
        if not self.current_preview_path:
            QMessageBox.warning(self, "알림", "쇼를 시작할 곡을 먼저 선택해주세요.")
            return
        is_image = self.current_preview_path.lower().endswith(
            tuple(self.image_extensions)
        )
        if not os.path.isfile(self.current_preview_path) or not is_image:
            QMessageBox.warning(
                self,
                "알림",
                "이미지 파일만 쇼를 시작할 수 있습니다. (.pls 파일 등은 불가)",
            )
            return

        # 싱글 쇼는 그냥 악보 모드로 간주
        single_data = [{"path": self.current_preview_path, "is_intermission": False}]
        self.open_viewer_window(single_data, 0)

    def update_file_count(self, path):
        total_files = 0
        root_index = self.tree.rootIndex()
        if root_index.isValid():
            total_files = self.count_visible_items(root_index)
        self.status_bar_label.setText(f"총 {total_files}개의 악보")

    def count_visible_items(self, parent_index):
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
        super().resizeEvent(event)
        if hasattr(self, "fade_overlay"):
            self.fade_overlay.setGeometry(self.rect())
        if (
            self.current_preview_path
            and self.preview_stack.currentWidget() == self.preview_scroll_area
        ):
            self.update_preview_panel(self.current_preview_path)

    def keyPressEvent(self, event):
        if self.list_widget.hasFocus() and event.key() == Qt.Key_Delete:
            self.delete_selected_items()
        else:
            super().keyPressEvent(event)

    def get_themes(self):
        return {
            "기본 (밝게)": {
                "base": "#FFFFFF",
                "window": "#FFFFFF",
                "text": "#000000",
                "button": "#F5F5F5",
                "button_text": "#000000",
                "highlight": "#D3D3D3",
                "highlight_text": "#000000",
                "border": "#CCCCCC",
            },
            "그린": {
                "base": "#F0FFF0",
                "window": "#E6F5E6",
                "text": "#003300",
                "button": "#90EE90",
                "button_text": "#003300",
                "highlight": "#3CB371",
                "highlight_text": "#FFFFFF",
                "border": "#2E8B57",
            },
            "어둡게": {
                "base": "#3E3E3E",
                "window": "#2D2D2D",
                "text": "#E0E0E0",
                "button": "#555555",
                "button_text": "#E0E0E0",
                "highlight": "#BB86FC",
                "highlight_text": "#000000",
                "border": "#1E1E1E",
            },
            "클래식 블루": {
                "base": "#EAF2F8",
                "window": "#D4E6F1",
                "text": "#1A5276",
                "button": "#A9CCE3",
                "button_text": "#154360",
                "highlight": "#5DADE2",
                "highlight_text": "#FFFFFF",
                "border": "#A9CCE3",
            },
        }

    def set_theme(self, theme_name):
        self.current_theme = theme_name
        self.apply_theme(theme_name)

    def apply_theme(self, theme_name):
        """전역 QSS를 적용합니다. (기능 변경 없이 디자인만 개선)"""
        theme = self.themes.get(theme_name, self.themes["기본 (밝게)"])

        stylesheet = f"""
            /* ===== Base ===== */
            QWidget {{
                background-color: {theme['window']};
                color: {theme['text']};
                font-family: '맑은 고딕';
                font-size: 10pt;
            }}
            QLabel#panelTitle {{
                font-size: 16pt;
                font-weight: 800;
            }}
            /* ===== Panels / Cards ===== */
            QTreeView, QListWidget, QLineEdit, QScrollArea, QTextEdit, QPlainTextEdit, QComboBox, QGroupBox {{
                background-color: {theme['base']};
                border: 1px solid {theme['border']};
                border-radius: 8px;
            }}
            QGroupBox {{
                margin-top: 14px;
                padding: 10px;
                font-weight: 700;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 6px;
            }}

            /* ===== Inputs ===== */
            QLineEdit {{
                padding: 6px 8px;
                selection-background-color: {theme['highlight']};
                selection-color: {theme['highlight_text']};
            }}
            QTextEdit, QPlainTextEdit {{
                padding: 8px;
            }}
            QComboBox {{
                padding: 6px 8px;
            }}
            QComboBox::drop-down {{
                border: 0px;
                width: 22px;
            }}

            /* ===== Splitter ===== */
            QSplitter::handle {{
                background-color: {theme['window']};
            }}

            /* ===== Lists / Trees ===== */
            QTreeView::item, QListWidget::item {{
                padding: 6px 8px;
                border-radius: 6px;
            }}
            QTreeView::item:hover, QListWidget::item:hover {{
                background-color: rgba(0, 0, 0, 0.06);
            }}
            QTreeView::item:selected, QListWidget::item:selected {{
                background-color: {theme['highlight']};
                color: {theme['highlight_text']};
            }}

            /* ===== Tabs ===== */
            QTabWidget::pane {{
                border-top: 1px solid {theme['border']};
                border-radius: 8px;
            }}
            QTabBar::tab {{
                background: {theme['button']};
                color: {theme['button_text']};
                border: 1px solid {theme['border']};
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                padding: 8px 12px;
                margin-right: 4px;
            }}
            QTabBar::tab:selected {{
                background: {theme['base']};
                color: {theme['text']};
            }}

            /* ===== Buttons (Base) ===== */
            QPushButton {{
                background-color: {theme['button']};
                color: {theme['button_text']};
                border: 1px solid {theme['border']};
                border-radius: 8px;
                padding: 8px 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {theme['highlight']};
                color: {theme['highlight_text']};
                border-color: {theme['highlight']};
            }}
            QPushButton:pressed {{
                background-color: rgba(0, 0, 0, 0.04);
            }}
            QPushButton:disabled {{
                opacity: 0.6;
            }}

            /* ===== Buttons by role ===== */
            QPushButton#primary {{
                background-color: {theme['highlight']};
                color: {theme['highlight_text']};
                border-color: {theme['highlight']};
            }}
            QPushButton#primary:hover {{
                background-color: rgba(0, 0, 0, 0.10);
                color: {theme['text']};
                border-color: {theme['border']};
            }}

            QPushButton#secondary {{
                background-color: {theme['button']};
                color: {theme['button_text']};
            }}

            QPushButton#ghost {{
                background-color: transparent;
                border: 1px solid {theme['border']};
            }}
            QPushButton#ghost:hover {{
                background-color: rgba(0, 0, 0, 0.06);
            }}

            QPushButton#danger {{
                background-color: #8b5a5a;
                color: white;
                border-color: #8b5a5a;
            }}
            QPushButton#danger:hover {{
                background-color: #734949;
                border-color: #734949;
            }}

            /* ===== Tooltip / Dialog ===== */
            QToolTip {{
                background-color: {theme['base']};
                color: {theme['text']};
                border: 1px solid {theme['border']};
                border-radius: 8px;
                padding: 6px;
            }}
            QDialog {{
                background-color: {theme['window']};
            }}
            
            /* ===== ScrollBar ===== */
            QScrollBar:vertical {{
                background: transparent;
                width: 10px;
                margin: 4px 2px 4px 2px;
            }}
            QScrollBar::handle:vertical {{
                background-color: rgba(0, 0, 0, 0.25);
                min-height: 40px;
                border-radius: 5px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: rgba(0, 0, 0, 0.40);
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{
                height: 0px;
                background: none;
            }}
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {{
                background: transparent;
            }}

            QScrollBar:horizontal {{
                background: transparent;
                height: 10px;
                margin: 2px 4px 2px 4px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: rgba(0, 0, 0, 0.25);
                min-width: 40px;
                border-radius: 5px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background-color: rgba(0, 0, 0, 0.40);
            }}
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal {{
                width: 0px;
                background: none;
            }}
            QScrollBar::add-page:horizontal,
            QScrollBar::sub-page:horizontal {{
                background: transparent;
            }}
        """

        self.setStyleSheet(stylesheet)
        self.preview_label.setStyleSheet(
            f"border: 1px solid {theme['border']}; border-radius: 8px;"
        )

    def update_zoom_label(self, value):

        self.initial_zoom_percentage = value
        self.zoom_label.setText(f"{value}%")

    def update_scroll_label(self, value):
        self.scroll_sensitivity = value
        self.scroll_label.setText(f"{value}px")

    def load_settings(self):
        self.sheet_music_path = "c:\\songs"
        self.playlist_path = "c:\\songs\\playlist"
        self.current_theme = "기본 (밝게)"
        self.initial_zoom_percentage = 60
        self.scroll_sensitivity = 30
        self.logo_image_path = ""
        self.drive_folder_id = "1fFN1w070XmwIHhbNxfuUzNXY7tAwWSzC"

        try:
            if not os.path.exists(self.sheet_music_path):
                os.makedirs(self.sheet_music_path)
            if not os.path.exists(self.playlist_path):
                os.makedirs(self.playlist_path)
        except OSError:
            pass
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, "r", encoding="utf-8") as f:
                    settings = json.load(f)

                    self.initial_zoom_percentage = settings.get("initial_zoom", 80)
                    self.sheet_music_path = settings.get(
                        "sheet_music_path", self.sheet_music_path
                    )
                    self.playlist_path = settings.get(
                        "playlist_path", self.playlist_path
                    )
                    self.current_theme = settings.get(
                        "current_theme", self.current_theme
                    )
                    self.scroll_sensitivity = settings.get("scroll_sensitivity", 30)
                    self.logo_image_path = settings.get("logo_image_path", "")

                    self.drive_folder_id = "1fFN1w070XmwIHhbNxfuUzNXY7tAwWSzC"
            else:
                self.save_settings()
        except (json.JSONDecodeError, TypeError, OSError) as e:
            print(f"설정 로드 오류 (기본값 사용): {e}")
            self.save_settings()

    def save_settings(self):
        settings = {
            "initial_zoom": self.initial_zoom_percentage,
            "sheet_music_path": self.sheet_music_path,
            "playlist_path": self.playlist_path,
            "current_theme": self.current_theme,
            "scroll_sensitivity": self.scroll_sensitivity,
            "logo_image_path": self.logo_image_path,
            "drive_folder_id": self.drive_folder_id,
        }
        try:
            with open(self.settings_file, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            QMessageBox.critical(
                self, "설정 저장 오류", f"설정을 저장하는 중 오류 발생: {e}"
            )

    def closeEvent(self, event):
        self.save_settings()
        if self.viewer:
            self.viewer.close()
        super().closeEvent(event)

    def change_sheet_music_folder(self):
        folder_path = QFileDialog.getExistingDirectory(
            self, "악보 폴더 선택", self.sheet_music_path
        )
        if folder_path and folder_path != self.sheet_music_path:
            self.sheet_music_path = folder_path
            self.path_label.setText(os.path.normpath(self.sheet_music_path))
            self.model.setRootPath(self.sheet_music_path)
            self.tree.setRootIndex(
                self.proxy_model.mapFromSource(self.model.index(self.sheet_music_path))
            )
            self.save_settings()

    def change_playlist_folder(self):
        folder_path = QFileDialog.getExistingDirectory(
            self, "플레이리스트 폴더 선택", self.playlist_path
        )
        if folder_path and folder_path != self.playlist_path:
            self.playlist_path = folder_path
            self.playlist_path_label.setText(os.path.normpath(self.playlist_path))
            self.playlist_model.setRootPath(self.playlist_path)
            self.playlist_tree.setRootIndex(
                self.playlist_proxy_model.mapFromSource(
                    self.playlist_model.index(self.playlist_path)
                )
            )
            self.save_settings()

    def change_logo_image(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "로고 이미지 선택",
            self.logo_image_path,
            "Images (*.png *.jpg *.jpeg *.bmp *.gif)",
        )
        if file_path:
            self.logo_image_path = file_path
            self.logo_path_label.setText(os.path.normpath(self.logo_image_path))
            self.save_settings()

    def on_search_text_changed(self, text):
        if self.favorites_view_active:
            self.search_input.blockSignals(True)
            self.search_input.clear()
            self.search_input.blockSignals(False)
            QMessageBox.information(
                self,
                "알림",
                "즐겨찾기 보기 모드에서는 검색할 수 없습니다.\n'전체 보기'로 전환 후 검색해주세요.",
            )
            return
        self.search_timer.start()

    def perform_search_filter(self):
        text = self.search_input.text()
        search_type = self.search_type_combo.currentText()
        if search_type == "파일이름":
            self.apply_search_filter(text)
        else:
            self.apply_lyrics_search(text)

    def perform_playlist_search_filter(self):
        text = self.playlist_search_input.text()
        self.apply_playlist_search_filter(text)

    def apply_search_filter(self, text):
        self.proxy_model.set_lyrics_filter(None)
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

    def apply_lyrics_search(self, text):
        if not text:
            self.proxy_model.set_lyrics_filter(None)
        else:
            matching_paths = self.search_lyrics_from_db(text)
            self.proxy_model.set_lyrics_filter(matching_paths)
        self.tree.setRootIndex(
            self.proxy_model.mapFromSource(self.model.index(self.model.rootPath()))
        )
        self.update_file_count(self.sheet_music_path)

    def apply_playlist_search_filter(self, text):
        keywords = text.strip().split()
        if not keywords:
            pattern = ""
        else:
            pattern = "".join([f"(?=.*{re.escape(keyword)})" for keyword in keywords])
        self.playlist_proxy_model.setFilterRegularExpression(
            QRegularExpression(pattern, QRegularExpression.CaseInsensitiveOption)
        )
        self.playlist_tree.setRootIndex(
            self.playlist_proxy_model.mapFromSource(
                self.playlist_model.index(self.playlist_model.rootPath())
            )
        )

    def reset_search_filter(self):
        self.search_input.clear()
        self.proxy_model.set_lyrics_filter(None)

    def reset_playlist_search_filter(self):
        self.playlist_search_input.clear()

    def change_sheet_sort_order(self, text):
        if text == "이름순 (오름차순)":
            self.proxy_model.setSortRole(Qt.DisplayRole)
            self.proxy_model.sort(0, Qt.AscendingOrder)
        elif text == "이름순 (내림차순)":
            self.proxy_model.setSortRole(Qt.DisplayRole)
            self.proxy_model.sort(0, Qt.DescendingOrder)
        elif text == "키(Key)순 (오름차순)":
            self.proxy_model.setSortRole(Qt.UserRole)
            self.proxy_model.sort(0, Qt.AscendingOrder)
        elif text == "키(Key)순 (내림차순)":
            self.proxy_model.setSortRole(Qt.UserRole)
            self.proxy_model.sort(0, Qt.DescendingOrder)

    def on_key_filter_changed(self, key_text):
        self.proxy_model.set_key_filter(key_text)
        self.update_file_count(self.sheet_music_path)

    def change_playlist_sort_order(self, text):
        if text == "이름순 (오름차순)":
            self.playlist_proxy_model.sort(0, Qt.AscendingOrder)
        elif text == "이름순 (내림차순)":
            self.playlist_proxy_model.sort(0, Qt.DescendingOrder)
        elif text == "수정날짜순 (최신)":
            self.playlist_proxy_model.sort(3, Qt.DescendingOrder)
        elif text == "수정날짜순 (오래된)":
            self.playlist_proxy_model.sort(3, Qt.AscendingOrder)

    def handle_tree_mouse_move(self, event, tree):
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
                        scaled = pixmap.scaledToWidth(
                            fixed_width, Qt.SmoothTransformation
                        )
                        tooltip = f'<img style="margin:0;padding:0;" src="{path}" width="{scaled.width()}" height="{scaled.height()}"/>'
                        QToolTip.showText(
                            event.globalPosition().toPoint() + QPoint(20, 20),
                            tooltip,
                            tree,
                        )
                    else:
                        QToolTip.hideText()
                elif path.lower().endswith(".pls"):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            data_list = json.load(f)

                        song_names = []
                        for d in data_list:
                            if isinstance(d, str):
                                song_names.append(
                                    os.path.splitext(os.path.basename(d))[0]
                                )
                            else:
                                name = os.path.splitext(
                                    os.path.basename(d.get("path", ""))
                                )[0]
                                if d.get("is_intermission"):
                                    name = f"☕ {name}"
                                song_names.append(name)

                        tooltip_text = "<b>플레이리스트:</b><br>" + "<br>".join(
                            f"- {name}" for name in song_names
                        )
                        QToolTip.showText(
                            event.globalPosition().toPoint() + QPoint(20, 20),
                            tooltip_text,
                            tree,
                        )
                    except Exception:
                        QToolTip.showText(
                            event.globalPosition().toPoint() + QPoint(20, 20),
                            "플레이리스트를 읽을 수 없습니다.",
                            tree,
                        )
                else:
                    QToolTip.hideText()
            else:
                QToolTip.hideText()
        elif not index.isValid():
            QToolTip.hideText()
            self.current_tooltip_index = QModelIndex()
        QTreeView.mouseMoveEvent(tree, event)

    def show_context_menu(self, pos):
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
                action_remove_favorite.triggered.connect(
                    self.remove_current_from_favorites
                )
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
        reply = QMessageBox.question(
            self,
            "파일 삭제 확인",
            f"'{os.path.basename(path)}' 파일을 정말로 삭제하시겠습니까?\n이 작업은 되돌릴 수 없습니다.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                os.remove(path)
            except OSError as e:
                QMessageBox.critical(
                    self,
                    "파일 삭제 오류",
                    f"파일을 삭제하는 중 오류가 발생했습니다: {e}",
                )

    def load_favorites(self):
        try:
            if os.path.exists(self.favorites_file):
                with open(self.favorites_file, "r", encoding="utf-8") as f:
                    self.favorites = set(json.load(f))
        except (json.JSONDecodeError, TypeError):
            self.favorites = set()
            QMessageBox.warning(
                self, "즐겨찾기 로드 오류", "즐겨찾기 파일을 불러오는 데 실패했습니다."
            )

    def save_favorites(self):
        try:
            with open(self.favorites_file, "w", encoding="utf-8") as f:
                json.dump(list(self.favorites), f, indent=4)
        except Exception as e:
            QMessageBox.critical(
                self, "즐겨찾기 저장 오류", f"즐겨찾기를 저장하는 중 오류 발생: {e}"
            )

    def add_current_to_favorites(self):
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
        try:
            with open(pls_path, "r", encoding="utf-8") as f:
                loaded_data = json.load(f)

            for entry in loaded_data:
                # 구버전/신버전 호환성
                if isinstance(entry, str):
                    path = entry
                    is_intermission = False
                else:
                    path = entry.get("path")
                    is_intermission = entry.get("is_intermission", False)

                full_path = os.path.normpath(os.path.join(self.sheet_music_path, path))

                if os.path.exists(full_path) and os.path.isfile(full_path):
                    base_name = os.path.splitext(os.path.basename(full_path))[0]

                    if is_intermission:
                        display_text = f"☕ [Intermission] {base_name}"
                    else:
                        item_text = (
                            f"⭐ {base_name}"
                            if full_path in self.favorites
                            else base_name
                        )
                        display_text = f"🎼 {item_text}"

                    item = QListWidgetItem(display_text)
                    item.setData(Qt.UserRole, full_path)
                    if is_intermission:
                        item.setData(Qt.UserRole + 1, True)

                    self.list_widget.addItem(item)
        except json.JSONDecodeError:
            QMessageBox.critical(
                self, "오류", f"올바른 .pls 파일이 아닙니다: {pls_path}"
            )
        except Exception as e:
            QMessageBox.critical(
                self, "오류", f".pls 파일을 불러오는 중 오류 발생: {e}"
            )

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
            QMessageBox.information(
                self, "정보", "폴더는 추가할 수 없습니다. 파일을 선택해 주세요."
            )

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

    def handle_list_click(self, item):
        pass

    # --- [추가] 찬양 리스트 아이템 표시 갱신/인터미션 토글 ---
    def _update_list_item_display(self, item: QListWidgetItem):
        """리스트 아이템의 텍스트를 현재 상태(인터미션 여부/즐겨찾기) 기준으로 갱신합니다."""
        path = item.data(Qt.UserRole)
        if not path:
            return
        base_name = os.path.splitext(os.path.basename(path))[0]
        is_intermission = bool(item.data(Qt.UserRole + 1))

        if is_intermission:
            item.setText(f"☕ [Intermission] {base_name}")
        else:
            item_text = f"⭐ {base_name}" if path in self.favorites else base_name
            item.setText(f"🎼 {item_text}")

    def toggle_selected_item_intermission(self):
        """현재 선택된 1개의 리스트 항목을 인터미션/악보로 전환합니다."""
        selected = self.list_widget.selectedItems()
        if len(selected) != 1:
            return
        item = selected[0]
        path = item.data(Qt.UserRole)

        if not (
            path
            and os.path.isfile(path)
            and path.lower().endswith(tuple(self.image_extensions))
        ):
            QMessageBox.information(
                self, "알림", "이미지 항목만 인터미션으로 전환할 수 있습니다."
            )
            return

        is_intm = bool(item.data(Qt.UserRole + 1))
        item.setData(Qt.UserRole + 1, (not is_intm))
        self._update_list_item_display(item)

    def show_list_widget_context_menu(self, pos):
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        menu = QMenu()
        action_start_show_current = QAction("현재 곡부터 쇼 시작", self)
        action_start_show_current.triggered.connect(self.start_show_from_current)
        menu.addAction(action_start_show_current)

        # [추가] 우클릭으로 인터미션 전환/해제
        selected = self.list_widget.selectedItems()
        if len(selected) == 1:
            sel_item = selected[0]
            path = sel_item.data(Qt.UserRole)
            is_image = (
                path
                and os.path.isfile(path)
                and path.lower().endswith(tuple(self.image_extensions))
            )
            if is_image:
                menu.addSeparator()
                is_intm = bool(sel_item.data(Qt.UserRole + 1))
                toggle_text = (
                    "인터미션 이미지로 변경" if not is_intm else "인터미션 해제(악보로)"
                )
                action_toggle_intm = QAction(toggle_text, self)
                action_toggle_intm.triggered.connect(
                    self.toggle_selected_item_intermission
                )
                menu.addAction(action_toggle_intm)

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
            self,
            "전체 삭제 확인",
            "정말로 모든 찬양 목록을 삭제하시겠습니까?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
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

    # --- 이전/다음 선택 메서드 ---
    def select_previous_item(self):
        row = self.list_widget.currentRow()
        if row > 0:
            self.list_widget.setCurrentRow(row - 1)
            # 뷰어가 켜져있으면 화면도 같이 넘김
            if self.viewer and self.viewer.isVisible():
                self.start_show_from_current()

    def select_next_item(self):
        row = self.list_widget.currentRow()
        if row < self.list_widget.count() - 1:
            self.list_widget.setCurrentRow(row + 1)
            # 뷰어가 켜져있으면 화면도 같이 넘김
            if self.viewer and self.viewer.isVisible():
                self.start_show_from_current()

    # --- [수정] 리스트 저장 시 인터미션 여부 포함 ---
    def save_list(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "리스트 저장", self.playlist_path, "Praise List Files (*.pls)"
        )
        if path:
            if not path.lower().endswith(".pls"):
                path += ".pls"

            items_to_save = []
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                data = {
                    "path": os.path.relpath(
                        item.data(Qt.UserRole), self.sheet_music_path
                    ),
                    "is_intermission": True if item.data(Qt.UserRole + 1) else False,
                }
                items_to_save.append(data)

            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(items_to_save, f, indent=4)
                QMessageBox.information(
                    self, "저장 완료", "리스트가 성공적으로 저장되었습니다."
                )
            except Exception as e:
                QMessageBox.critical(
                    self, "저장 오류", f"리스트를 저장하는 중 오류가 발생했습니다: {e}"
                )

    # --- [수정] 리스트 불러오기 (호환성 유지) ---
    def load_list(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "리스트 불러오기",
            self.playlist_path,
            "Praise List Files (*.pls);;All Files (*)",
        )
        if path:
            self.list_widget.clear()
            self._add_paths_from_pls(path)
            QMessageBox.information(
                self, "불러오기 완료", "리스트가 성공적으로 불러와졌습니다."
            )

    def preview_selected_file(self, current_index, tree_view):
        if not current_index.isValid() or current_index.column() != 0:
            self.current_preview_path = None
            self.update_preview_panel(None)
            self.load_metadata_to_inspector(None)
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
        is_song_file = (
            (tree_view == self.tree)
            and (path and os.path.isfile(path))
            and path.lower().endswith(tuple(self.image_extensions))
        )
        if is_song_file:
            self.load_metadata_to_inspector(path)
        else:
            self.load_metadata_to_inspector(None)

    def update_preview_panel(self, path):
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
                    scaled_pixmap = pixmap.scaledToWidth(
                        int(preview_width * 0.95), Qt.SmoothTransformation
                    )
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
                with open(path, "r", encoding="utf-8") as f:
                    data_list = json.load(f)

                if not data_list:
                    item = QListWidgetItem("비어 있는 플레이리스트입니다.")
                    item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                    self.preview_list_widget.addItem(item)
                    return

                for entry in data_list:
                    if isinstance(entry, str):
                        rel_p = entry
                        is_intermission = False
                    else:
                        rel_p = entry.get("path")
                        is_intermission = entry.get("is_intermission", False)

                    p = os.path.normpath(os.path.join(self.sheet_music_path, rel_p))
                    base_name = os.path.splitext(os.path.basename(p))[0]
                    if os.path.exists(p) and os.path.isfile(p):
                        if is_intermission:
                            display_text = f"☕ [Intermission] {base_name}"
                        else:
                            display_text = f"🎼 {base_name}"
                        item = QListWidgetItem(display_text)
                        item.setData(Qt.UserRole, p)
                        self.preview_list_widget.addItem(item)
                    else:
                        item = QListWidgetItem(f"❌ {base_name} (파일 없음)")
                        item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
                        self.preview_list_widget.addItem(item)
            except Exception as e:
                self.preview_stack.setCurrentWidget(self.preview_scroll_area)
                self.preview_label.setText(
                    f"플레이리스트 파일을 읽는 중 오류 발생:\n{e}"
                )
                self.preview_label.setAlignment(Qt.AlignCenter)
        else:
            self.preview_stack.setCurrentWidget(self.preview_scroll_area)
            self.preview_label.setText(
                "선택된 파일은 이미지 또는 .pls 파일이 아닙니다."
            )
            self.preview_label.setAlignment(Qt.AlignCenter)

    def run_google_sync(self):
        # 1. 사전 체크
        key_file = os.path.join(self.app_dir, "service_account.json")
        if not os.path.exists(key_file):
            QMessageBox.critical(
                self,
                "설정 오류",
                f"서비스 계정 키 파일(service_account.json)이 없습니다.\n"
                f"프로그램 폴더에 키 파일을 넣어주세요.\n경로: {self.app_dir}",
            )
            return

        if not self.drive_folder_id or "여기에" in self.drive_folder_id:
            QMessageBox.warning(
                self,
                "설정 확인",
                "설정 파일(settings.json) 또는 코드의 load_settings에\n구글 드라이브 폴더 ID가 올바른지 확인해주세요.",
            )
            return

        # 2. UI 준비 (다이얼로그 표시)
        self.sync_dialog = SyncProgressDialog(self)
        self.sync_dialog.show()

        # 3. 백그라운드 워커 준비
        syncer_helper = GoogleDriveSync(
            key_file, self.sheet_music_path, self.drive_folder_id, self.app_dir
        )
        self.sync_thread = SyncThread(syncer_helper)

        # 4. 시그널 연결
        self.sync_thread.log_signal.connect(self.sync_dialog.append_log)
        self.sync_thread.progress_signal.connect(self.sync_dialog.update_progress)
        self.sync_thread.finished_signal.connect(self.on_sync_finished)

        # 5. 시작
        self.sync_thread.start()

    def on_sync_finished(self, success, download_count, db_updated, msg):
        self.sync_dialog.finish_sync(success, msg)
        self.sync_dialog.append_log("-" * 30)
        self.sync_dialog.append_log(f"결과: {msg}")
        if success:
            if download_count > 0:
                self.sync_dialog.append_log(f"-> {download_count}개의 새 악보 저장됨")
                self.model.setRootPath("")
                self.model.setRootPath(self.sheet_music_path)

            if db_updated:
                self.sync_dialog.append_log("-> 곡 정보(DB) 최신화됨")
                self.metadata_cache = self.load_all_metadata_from_db()
                self.proxy_model.invalidate()
                self.load_metadata_to_inspector(self.current_preview_path)

        self.status_bar_label.setText(msg)

    # --- [듀얼 모니터] 관련 메서드들 ---
    def open_viewer_window(self, playlist_data, start_index):
        """쇼창(Viewer)을 열거나 업데이트합니다. 이제 경로 리스트가 아닌 data list를 받습니다."""
        if not playlist_data:
            QMessageBox.warning(self, "오류", "표시할 이미지가 없습니다.")
            return

        # 뷰어가 이미 열려있으면 내용만 업데이트
        if self.viewer and self.viewer.isVisible():
            self.viewer.update_content(
                playlist_data, start_index, self.initial_zoom_percentage
            )
            self.viewer.activateWindow()
            return

        # 뷰어가 닫혀있으면 새로 생성
        self.viewer = FullScreenViewer(
            playlist_data,
            self.initial_zoom_percentage,
            start_index=start_index,
            scroll_sensitivity=self.scroll_sensitivity,
            logo_path=self.logo_image_path,
        )

        self.viewer.closed.connect(self.on_viewer_closed)

        # 사용자가 선택한 모니터 인덱스 가져오기
        screen_index = self.monitor_combo.currentIndex()
        screens = QApplication.screens()

        if 0 <= screen_index < len(screens):
            target_screen = screens[screen_index]
            self.viewer.move(target_screen.geometry().topLeft())
            self.viewer.showFullScreen()
            if self.viewer.windowHandle():
                self.viewer.windowHandle().setScreen(target_screen)
        else:
            self.viewer.showFullScreen()

        self.btn_toggle_dual_viewer.setChecked(True)
        self.btn_toggle_dual_viewer.setText("쇼창 끄기")

    def toggle_dual_monitor_viewer(self, checked):
        if checked:
            self.start_show_from_current()
        else:
            if self.viewer:
                self.viewer.close()

    def remote_toggle_black(self):
        if self.viewer and self.viewer.isVisible():
            self.viewer.toggle_black_screen()

    def remote_toggle_logo(self):
        if self.viewer and self.viewer.isVisible():
            self.viewer.toggle_logo_screen()

    def on_viewer_closed(self):
        self.btn_toggle_dual_viewer.setChecked(False)
        self.btn_toggle_dual_viewer.setText("쇼창 켜기")
        self.viewer = None

    def _get_playlist_data(self):
        """리스트 위젯에서 실행 데이터를 추출합니다."""
        data = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            path = item.data(Qt.UserRole)
            is_intm = item.data(Qt.UserRole + 1) == True
            data.append({"path": path, "is_intermission": is_intm})
        return data

    def start_show(self):
        data = self._get_playlist_data()
        self.open_viewer_window(data, 0)

    def start_show_from_current(self):
        data = self._get_playlist_data()
        start_index = self.list_widget.currentRow()
        if start_index < 0:
            start_index = 0
        self.open_viewer_window(data, start_index)


class FullScreenViewer(QWidget):
    # 창이 닫힐 때 메인 윈도우에 알리기 위한 시그널
    closed = Signal()

    def __init__(
        self,
        playlist_data,
        initial_zoom_percentage=80,
        start_index=0,
        scroll_sensitivity=30,
        logo_path="",
    ):
        super().__init__()
        self.playlist_data = playlist_data
        self.current_index = start_index
        if not (0 <= self.current_index < len(self.playlist_data)):
            self.current_index = 0

        self.initial_zoom = initial_zoom_percentage / 100.0
        self.zoom = self.initial_zoom
        self.scroll_step = scroll_sensitivity
        self.show_ended = False
        self.logo_path = logo_path

        self.setWindowTitle("악보 쇼 (쇼화면)")
        self.setFocusPolicy(Qt.StrongFocus)

        # 1. 악보 화면 (Scroll Area)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFocusPolicy(Qt.NoFocus)
        self.scroll_area.setWidget(self.image_label)

        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        palette = self.scroll_area.palette()
        palette.setColor(
            QPalette.Window, QColor("white")
        )  # 배경 검정으로 통일 (인터미션 시 보기 좋게)
        self.scroll_area.setPalette(palette)
        self.scroll_area.setAutoFillBackground(True)

        # 2. 엔드 스크린
        self.end_screen_widget = QWidget()
        end_layout = QVBoxLayout(self.end_screen_widget)
        end_layout.addStretch()
        end_message_label = QLabel("악보 쇼가 끝났습니다.")
        end_font = QFont("맑은 고딕", 16)
        end_message_label.setFont(end_font)
        end_message_label.setAlignment(Qt.AlignCenter)
        end_message_label.setStyleSheet("color: white;")
        end_layout.addWidget(end_message_label)
        self.end_screen_widget.setStyleSheet("background-color: black;")

        # 3. 블랙 스크린 위젯
        self.black_screen_widget = QWidget()
        self.black_screen_widget.setStyleSheet("background-color: black;")

        # 4. 로고 스크린 위젯
        self.logo_screen_widget = QLabel()
        self.logo_screen_widget.setAlignment(Qt.AlignCenter)
        self.logo_screen_widget.setStyleSheet("background-color: black;")
        if self.logo_path and os.path.isfile(self.logo_path):
            logo_pix = QPixmap(self.logo_path)
            if not logo_pix.isNull():
                self.logo_pixmap_original = logo_pix
            else:
                self.logo_screen_widget.setText("로고 이미지를 불러올 수 없습니다.")
                self.logo_screen_widget.setStyleSheet(
                    "color: white; background-color: black;"
                )
        else:
            self.logo_screen_widget.setText("로고 이미지가 설정되지 않았습니다.")
            self.logo_screen_widget.setStyleSheet(
                "color: white; background-color: black;"
            )

        # 스택 레이아웃 구성
        self.main_layout = QStackedLayout()
        self.main_layout.addWidget(self.scroll_area)  # Index 0
        self.main_layout.addWidget(self.end_screen_widget)  # Index 1
        self.main_layout.addWidget(self.black_screen_widget)  # Index 2
        self.main_layout.addWidget(self.logo_screen_widget)  # Index 3

        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.main_layout)

        # --- [추가] 밝기 변화(페이드) 전환 오버레이 ---
        self._is_transitioning = False
        self.fade_overlay = QWidget(self)
        self.fade_overlay.setStyleSheet("background-color: black;")
        self.fade_overlay.setGeometry(self.rect())
        self.fade_overlay.hide()

        self.fade_effect = QGraphicsOpacityEffect(self.fade_overlay)
        self.fade_overlay.setGraphicsEffect(self.fade_effect)
        self.fade_effect.setOpacity(0.0)

        self.fade_anim = QPropertyAnimation(self.fade_effect, b"opacity", self)
        self.fade_anim.setEasingCurve(QEasingCurve.InOutQuad)
        self.fade_anim.setDuration(300)

        self.scroll_area.viewport().installEventFilter(self)

        self.next_song_label = QLabel(self)
        self.next_song_label.setStyleSheet(
            "background-color: rgba(0, 0, 0, 180); color: white; font-size: 14pt; padding: 5px; border-radius: 3px;"
        )
        self.next_song_label.hide()

    def update_content(self, playlist_data, start_index, initial_zoom_percentage):
        self.playlist_data = playlist_data
        self.current_index = start_index
        if not (0 <= self.current_index < len(self.playlist_data)):
            self.current_index = 0

        self.initial_zoom = initial_zoom_percentage / 100.0
        self.zoom = self.initial_zoom

        self.show_ended = False
        self.main_layout.setCurrentWidget(self.scroll_area)
        self.load_image()

        self.scroll_area.verticalScrollBar().setValue(0)
        self.scroll_area.horizontalScrollBar().setValue(0)

    def closeEvent(self, event):
        self.closed.emit()
        super().closeEvent(event)

    def load_image(self):
        if not self.playlist_data:
            self.image_label.clear()
            return

        self.zoom = self.initial_zoom
        current_data = self.playlist_data[self.current_index]
        path = current_data["path"]
        is_intermission = current_data["is_intermission"]

        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.image_label.setText("이미지를 불러올 수 없습니다.")
            return

        view_size = self.scroll_area.viewport().size()

        if is_intermission:
            # --- 인터미션 모드: 화면 중앙에 꽉 차게 (KeepAspectRatio) ---
            scaled = pixmap.scaled(
                view_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.image_label.setPixmap(scaled)
            self.image_label.setAlignment(Qt.AlignCenter)
            # 인터미션은 스크롤 없이
            self.scroll_area.verticalScrollBar().setValue(0)
            self.scroll_area.horizontalScrollBar().setValue(0)
            self.next_song_label.hide()
        else:
            # --- 일반 악보 모드: 가로 폭 기준 스크롤 ---
            self.image_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
            viewer_width = view_size.width()
            scaled = pixmap.scaledToWidth(
                int(viewer_width * self.zoom), Qt.SmoothTransformation
            )
            self.image_label.setPixmap(scaled)
            self.update_next_song_label()

    def load_image_with_current_zoom(self):
        if not self.playlist_data:
            self.image_label.clear()
            return

        current_data = self.playlist_data[self.current_index]
        path = current_data["path"]
        is_intermission = current_data["is_intermission"]

        pixmap = QPixmap(path)
        if pixmap.isNull():
            return

        view_size = self.scroll_area.viewport().size()

        if is_intermission:
            # 인터미션은 줌 영향 안 받음 (항상 핏)
            scaled = pixmap.scaled(
                view_size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.image_label.setPixmap(scaled)
            self.image_label.setAlignment(Qt.AlignCenter)
            self.next_song_label.hide()
        else:
            viewer_width = view_size.width()
            scaled = pixmap.scaledToWidth(
                int(viewer_width * self.zoom), Qt.SmoothTransformation
            )
            self.image_label.setPixmap(scaled)
            self.image_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
            self.update_next_song_label()

    def _run_brightness_transition(self, after_fade_in_callback):
        """화면을 잠깐 어둡게(밝기 변화) 했다가 복귀시키는 전환."""
        if self._is_transitioning:
            # 이미 전환 중이면 콜백만 실행
            after_fade_in_callback()
            return

        self._is_transitioning = True
        self.fade_overlay.setGeometry(self.rect())
        self.fade_overlay.show()
        self.fade_overlay.raise_()
        self.fade_anim.stop()

        def _fade_out_to_black():
            self.fade_anim.stop()
            self.fade_anim.setStartValue(0.0)
            self.fade_anim.setEndValue(1.0)

            def _on_faded_to_black():
                try:
                    after_fade_in_callback()
                finally:
                    # 다시 밝아지기
                    self.fade_anim.finished.disconnect(_on_faded_to_black)
                    self.fade_anim.stop()
                    self.fade_anim.setStartValue(1.0)
                    self.fade_anim.setEndValue(0.0)

                    def _on_fade_back_done():
                        self.fade_anim.finished.disconnect(_on_fade_back_done)
                        self.fade_overlay.hide()
                        self._is_transitioning = False

                    self.fade_anim.finished.connect(_on_fade_back_done)
                    self.fade_anim.start()

            self.fade_anim.finished.connect(_on_faded_to_black)
            self.fade_anim.start()

        _fade_out_to_black()

    def _navigate_to(self, new_index: int):
        if not (0 <= new_index < len(self.playlist_data)):
            return

        prev_is_intm = bool(self.playlist_data[self.current_index]["is_intermission"])
        next_is_intm = bool(self.playlist_data[new_index]["is_intermission"])

        self.current_index = new_index

        def _do_load():
            self.load_image()
            self.scroll_area.verticalScrollBar().setValue(0)
            self.scroll_area.horizontalScrollBar().setValue(0)

        # 인터미션 <-> 악보 전환일 때만 페이드 적용
        if prev_is_intm != next_is_intm:
            self._run_brightness_transition(_do_load)
        else:
            _do_load()

    def fit_to_height(self):
        if not self.playlist_data:
            return
        path = self.playlist_data[self.current_index]["path"]
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return
        viewer_height = self.scroll_area.viewport().height()
        scaled = pixmap.scaledToHeight(viewer_height, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled)
        self.scroll_area.verticalScrollBar().setValue(0)
        self.scroll_area.horizontalScrollBar().setValue(0)
        self.update_next_song_label()

    def showEvent(self, event):
        super().showEvent(event)
        self.load_image()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "fade_overlay"):
            self.fade_overlay.setGeometry(self.rect())
        if self.main_layout.currentWidget() == self.scroll_area:
            self.load_image()
        if self.main_layout.currentWidget() == self.logo_screen_widget and hasattr(
            self, "logo_pixmap_original"
        ):
            self.display_logo_scaled()

    def display_logo_scaled(self):
        if hasattr(self, "logo_pixmap_original"):
            scaled = self.logo_pixmap_original.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.logo_screen_widget.setPixmap(scaled)

    def show_first_alert(self):
        pass

    def show_end_screen(self):
        self.show_ended = True
        self.main_layout.setCurrentWidget(self.end_screen_widget)
        self.next_song_label.hide()

    def return_to_last_slide(self):
        self.show_ended = False
        self.main_layout.setCurrentWidget(self.scroll_area)
        self.update_next_song_label()

    def toggle_black_screen(self):
        def _do_switch():
            if self.main_layout.currentWidget() == self.black_screen_widget:
                # 블랙 -> 악보로 복귀
                self.main_layout.setCurrentWidget(self.scroll_area)
                self.load_image_with_current_zoom()  # 상태 복구
            else:
                # 악보 -> 블랙
                self.main_layout.setCurrentWidget(self.black_screen_widget)
                self.next_song_label.hide()

        # 페이드 적용
        self._run_brightness_transition(_do_switch)

    def toggle_logo_screen(self):
        def _do_switch():
            if self.main_layout.currentWidget() == self.logo_screen_widget:
                # 로고 -> 악보로 복귀
                self.main_layout.setCurrentWidget(self.scroll_area)
                self.load_image_with_current_zoom()
            else:
                # 악보 -> 로고
                self.main_layout.setCurrentWidget(self.logo_screen_widget)
                self.display_logo_scaled()
                self.next_song_label.hide()

        # 페이드 적용
        self._run_brightness_transition(_do_switch)

    def update_next_song_label(self):
        if self.main_layout.currentWidget() != self.scroll_area:
            self.next_song_label.hide()
            return

        # 현재 곡이 인터미션이면 다음곡 라벨 안보여줌
        if self.playlist_data[self.current_index]["is_intermission"]:
            self.next_song_label.hide()
            return

        next_index = self.current_index + 1
        if 0 <= next_index < len(self.playlist_data):
            path = self.playlist_data[next_index]["path"]
            is_intm = self.playlist_data[next_index]["is_intermission"]
            base_name = os.path.splitext(os.path.basename(path))[0]

            if is_intm:
                text = f"NEXT: ☕ {base_name}"
            else:
                text = f"NEXT: {base_name}"

            self.next_song_label.setText(text)
            self.next_song_label.adjustSize()
            margin = 10
            x = self.width() - self.next_song_label.width() - margin
            y = margin
            self.next_song_label.move(x, y)
            self.next_song_label.show()
            self.next_song_label.raise_()
        else:
            self.next_song_label.hide()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.main_layout.currentWidget() in [
                self.black_screen_widget,
                self.logo_screen_widget,
            ]:
                self.main_layout.setCurrentWidget(self.scroll_area)
                self.load_image_with_current_zoom()
            else:
                self.close()
            return

        if event.key() == Qt.Key_B:
            self.toggle_black_screen()
            return

        if event.key() == Qt.Key_L:
            self.toggle_logo_screen()
            return

        if self.show_ended:
            if event.key() in (Qt.Key_PageDown, Qt.Key_Right, Qt.Key_Space):
                self.close()
            elif event.key() in (Qt.Key_PageUp, Qt.Key_Left):
                self.return_to_last_slide()
            return

        if event.key() in (Qt.Key_PageDown, Qt.Key_Right, Qt.Key_Space):
            if self.current_index < len(self.playlist_data) - 1:
                self._navigate_to(self.current_index + 1)
            else:
                self.show_end_screen()
        elif event.key() in (Qt.Key_PageUp, Qt.Key_Left):
            if self.current_index > 0:
                self._navigate_to(self.current_index - 1)
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
            if self.current_index < len(self.playlist_data) - 1:
                self._navigate_to(self.current_index + 1)
            else:
                self.show_end_screen()
        elif event.button() == Qt.RightButton:
            if self.current_index > 0:
                self._navigate_to(self.current_index - 1)
            else:
                self.show_first_alert()

    def eventFilter(self, obj, event):
        if obj == self.scroll_area.viewport() and event.type() == QEvent.Wheel:
            if self.show_ended:
                return True
            if event.modifiers() == Qt.ControlModifier:
                if event.angleDelta().y() > 0:
                    self.zoom = min(2.0, self.zoom + 0.1)
                else:
                    self.zoom = max(0.1, self.zoom - 0.1)
                self.load_image_with_current_zoom()
                return True
            else:
                v_scroll_bar = self.scroll_area.verticalScrollBar()
                scroll_amount = self.scroll_step
                if event.angleDelta().y() > 0:
                    new_value = v_scroll_bar.value() - scroll_amount
                    v_scroll_bar.setValue(max(v_scroll_bar.minimum(), new_value))
                else:
                    new_value = v_scroll_bar.value() + scroll_amount
                    v_scroll_bar.setValue(min(v_scroll_bar.maximum(), new_value))
                return True
        return super().eventFilter(obj, event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    viewer = PraiseSheetViewer()
    viewer.showMaximized()
    sys.exit(app.exec())
