import sys
import os
import json
import webbrowser
import urllib.parse
import numpy as np 
import cv2
import requests

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLineEdit, QLabel, QFileDialog, QMessageBox, QCheckBox, QFrame,
    QDialog, QDialogButtonBox, QScrollArea
)
from PySide6.QtCore import (
    Qt, QRect, QTimer, QPoint, QBuffer, QIODevice, QThread, Signal,
    QByteArray 
)
from PySide6.QtGui import (
    QColor, QPainter, QPen, QGuiApplication, QPixmap, QCursor, 
    QShortcut, QKeySequence, QImage, QFont, QIcon
)

# --- [설정] 구글 앱스 스크립트 URL ---
# (본인의 스크립트 URL이 맞는지 확인하세요)
GOOGLE_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbxuPGvTqpZVFAft5DreWW4m7iQK_6LLSthaVt_ei31I3JwV35DpAEv4nrJbubghzgIf/exec" 

# --- 헬퍼 함수 ---
def qpixmap_to_cv_gray(pixmap):
    qimg = pixmap.toImage()
    qimg = qimg.convertToFormat(QImage.Format.Format_Grayscale8)
    width = qimg.width()
    height = qimg.height()
    bytes_per_line = qimg.bytesPerLine()
    ptr = qimg.bits()
    if hasattr(ptr, 'setsize'): 
        ptr.setsize(height * bytes_per_line)
    arr = np.array(ptr).reshape(height, bytes_per_line)
    return arr[:, :width]

def load_settings(app_dir):
    settings_file = os.path.join(app_dir, "settings.json")
    default_path = "c:\\songs"
    if os.path.exists(settings_file):
        try:
            with open(settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                return settings.get('sheet_music_path', default_path)
        except:
            pass
    return default_path

# --- [핵심] HTTP POST 업로드 스레드 ---
class UploadThread(QThread):
    finished_signal = Signal(bool, str)

    def __init__(self, script_url, pixmap, file_name):
        super().__init__()
        self.script_url = script_url
        self.pixmap = pixmap
        self.file_name = file_name

    def run(self):
        try:
            # 1. 이미지를 메모리 상에서 JPG Base64 문자열로 변환
            byte_array = QByteArray()
            buffer = QBuffer(byte_array)
            buffer.open(QIODevice.WriteOnly)
            self.pixmap.save(buffer, "JPG")
            base64_data = byte_array.toBase64().data().decode('utf-8')

            # 2. 전송할 데이터 포장
            payload = {
                'filename': self.file_name,
                'filedata': base64_data
            }

            # 3. 구글 앱스 스크립트로 전송 (POST)
            response = requests.post(self.script_url, json=payload)
            
            # 4. 결과 확인
            if response.status_code == 200:
                res_json = response.json()
                if res_json.get("result") == "success":
                    self.finished_signal.emit(True, f"업로드 성공: {self.file_name}")
                else:
                    self.finished_signal.emit(False, f"구글 오류: {res_json.get('error')}")
            else:
                self.finished_signal.emit(False, f"통신 오류: {response.status_code}")

        except Exception as e:
            self.finished_signal.emit(False, f"업로드 실패: {str(e)}")

# --- 저장 확인 다이얼로그 ---
class ConfirmDialog(QDialog):
    def __init__(self, pixmap, default_name, current_dir, parent=None):
        super().__init__(parent)
        self.setWindowTitle("캡처/파일 저장 확인") 
        self.resize(700, 600)
        self.current_dir = current_dir
        self.original_pixmap = pixmap
        
        # 부모 창의 아이콘이 있다면 다이얼로그에도 적용
        if parent and parent.windowIcon():
            self.setWindowIcon(parent.windowIcon())

        layout = QVBoxLayout(self)
        
        # 이미지 크기 정보 표시
        w = self.original_pixmap.width()
        h = self.original_pixmap.height()
        size_label = QLabel(f"📏 이미지 크기: <b>{w} x {h}</b> px")
        size_label.setAlignment(Qt.AlignCenter)
        size_label.setStyleSheet("font-size: 11pt; color: #333; margin-bottom: 5px;")
        layout.addWidget(size_label)

        # 이미지 미리보기
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.img_label = QLabel()
        self.img_label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.update_preview_image()
        self.scroll.setWidget(self.img_label)
        layout.addWidget(self.scroll, 1)
        
        # 폴더 선택
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("저장 폴더:"))
        self.dir_edit = QLineEdit(self.current_dir)
        self.dir_edit.setReadOnly(True) 
        dir_layout.addWidget(self.dir_edit)
        self.btn_change_dir = QPushButton("폴더 변경")
        self.btn_change_dir.clicked.connect(self.change_folder)
        dir_layout.addWidget(self.btn_change_dir)
        layout.addLayout(dir_layout)
        
        # 파일명 입력
        form_layout = QHBoxLayout()
        form_layout.addWidget(QLabel("저장 이름:"))
        self.name_edit = QLineEdit(default_name)
        self.name_edit.setPlaceholderText("파일명을 입력하세요")
        form_layout.addWidget(self.name_edit)
        form_layout.addWidget(QLabel(".jpg"))
        layout.addLayout(form_layout)
        
        # 구글 드라이브 업로드 체크박스
        self.chk_upload = QCheckBox("☁️ 구글 드라이브에 자동 업로드")
        self.chk_upload.setChecked(True)
        self.chk_upload.setStyleSheet("font-weight: bold; color: #0078D7;")
        layout.addWidget(self.chk_upload)

        btn_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btn_box.button(QDialogButtonBox.Save).setText("저장 및 처리 (Enter)")
        btn_box.button(QDialogButtonBox.Cancel).setText("취소 (Esc)")
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
        self.name_edit.selectAll()
        self.name_edit.setFocus()

    def update_preview_image(self):
        available_width = self.width() - 40 
        if self.original_pixmap.width() > available_width:
            scaled = self.original_pixmap.scaledToWidth(available_width, Qt.SmoothTransformation)
            self.img_label.setPixmap(scaled)
        else:
            self.img_label.setPixmap(self.original_pixmap)
    def resizeEvent(self, event):
        self.update_preview_image()
        super().resizeEvent(event)
    def change_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "저장할 폴더 선택", self.current_dir)
        if folder:
            self.current_dir = folder
            self.dir_edit.setText(folder)
    def get_data(self):
        return self.current_dir, self.name_edit.text().strip(), self.chk_upload.isChecked()

# --- 캡처 오버레이 ---
class SnippingWidget(QWidget):
    def __init__(self, parent=None, master_rect=None, prev_pixmap=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowState(Qt.WindowFullScreen)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus) 
        self.start_point = None
        self.end_point = None
        self.is_snipping = False
        self.master_rect = master_rect 
        self.guide_pixmap = None
        self.guide_cv_gray = None
        self.matched_y = None 
        self.is_matched = False
        if prev_pixmap and master_rect:
            h = prev_pixmap.height()
            crop_h = min(150, h) 
            self.guide_pixmap = prev_pixmap.copy(0, h - crop_h, prev_pixmap.width(), crop_h)
            try:
                self.guide_cv_gray = qpixmap_to_cv_gray(self.guide_pixmap)
            except Exception:
                self.guide_cv_gray = None
        screen = QGuiApplication.primaryScreen()
        self.original_pixmap = screen.grabWindow(0)
        self.screen_cv_gray = None 
        if self.guide_cv_gray is not None:
             try:
                self.screen_cv_gray = qpixmap_to_cv_gray(self.original_pixmap)
             except Exception:
                pass
        self.overlay_color = QColor(0, 0, 0, 100) 
        self.shortcut_esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        self.shortcut_esc.activated.connect(self.close)
    def showEvent(self, event):
        self.setFocus()
        self.grabKeyboard()
        super().showEvent(event)
    def closeEvent(self, event):
        self.releaseKeyboard()
        if self.parent():
            self.parent().showNormal()
            self.parent().activateWindow()
        super().closeEvent(event)
    def detect_overlap(self, cursor_y):
        if self.guide_cv_gray is None or self.screen_cv_gray is None or not self.master_rect:
            return None
        search_range = 100
        x = self.master_rect.x()
        w = self.master_rect.width()
        start_y = max(0, cursor_y - self.guide_pixmap.height() - search_range)
        end_y = min(self.screen_cv_gray.shape[0], cursor_y + search_range)
        if end_y <= start_y + self.guide_cv_gray.shape[0]:
            return None
        roi = self.screen_cv_gray[start_y:end_y, x:x+w]
        if roi.shape[0] < self.guide_cv_gray.shape[0] or roi.shape[1] != self.guide_cv_gray.shape[1]:
            return None
        res = cv2.matchTemplate(roi, self.guide_cv_gray, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
        if max_val > 0.8:
            return start_y + max_loc[1]
        return None
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.drawPixmap(0, 0, self.original_pixmap)
        painter.fillRect(self.rect(), self.overlay_color)
        if self.master_rect:
            x = self.master_rect.x()
            w = self.master_rect.width()
            h = self.height()
            guide_rect = QRect(x, 0, w, h)
            painter.drawPixmap(guide_rect, self.original_pixmap, guide_rect)
            pen = QPen(QColor(255, 0, 0), 2, Qt.DashLine)
            painter.setPen(pen)
            painter.drawLine(x, 0, x, h)
            painter.drawLine(x+w, 0, x+w, h)
            if self.guide_pixmap and not self.is_snipping:
                cursor_y = self.mapFromGlobal(QCursor.pos()).y()
                guide_h = self.guide_pixmap.height()
                if self.is_matched and self.matched_y is not None:
                    draw_y = self.matched_y
                    pen_guide = QPen(QColor(0, 255, 0), 3, Qt.SolidLine)
                    painter.setPen(pen_guide)
                    painter.drawRect(x, draw_y, w, guide_h)
                    painter.setPen(QColor(0, 255, 0))
                    painter.setFont(painter.font())
                    painter.drawText(x + 10, draw_y - 10, "⚡ 위치 일치")
                    painter.setOpacity(0.8)
                else:
                    draw_y = cursor_y - guide_h
                    pen_guide = QPen(QColor(0, 255, 255), 2, Qt.SolidLine)
                    painter.setPen(pen_guide)
                    painter.drawLine(x, cursor_y, x+w, cursor_y)
                    painter.setOpacity(0.5)
                painter.drawPixmap(x, draw_y, self.guide_pixmap)
                painter.setOpacity(1.0)
        if self.start_point and self.end_point:
            current_rect = self.get_current_selection_rect()
            painter.drawPixmap(current_rect, self.original_pixmap, current_rect)
            pen = QPen(QColor(255, 0, 0), 2)
            painter.setPen(pen)
            painter.drawRect(current_rect)
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)
    def get_current_selection_rect(self):
        if not self.start_point or not self.end_point:
            return QRect()
        rect = QRect(self.start_point, self.end_point).normalized()
        if self.master_rect:
            rect.setX(self.master_rect.x())
            rect.setWidth(self.master_rect.width())
        return rect
    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.close()
            return
        if event.button() == Qt.LeftButton:
            current_pos = event.position().toPoint()
            if self.is_matched and self.matched_y is not None:
                snap_y = self.matched_y + self.guide_pixmap.height()
                self.start_point = QPoint(current_pos.x(), snap_y)
                self.end_point = QPoint(current_pos.x(), snap_y)
            else:
                self.start_point = current_pos
                self.end_point = current_pos
            self.is_snipping = True
            self.update()
    def mouseMoveEvent(self, event):
        if not self.is_snipping:
            cursor_pos = event.position().toPoint()
            detected_y = self.detect_overlap(cursor_pos.y())
            if detected_y is not None:
                self.is_matched = True
                self.matched_y = detected_y
            else:
                self.is_matched = False
                self.matched_y = None
            self.update()
            return
        if self.is_snipping:
            self.end_point = event.position().toPoint()
            self.update()
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_snipping = False
            final_rect = self.get_current_selection_rect()
            self.close()
            if final_rect.width() > 10 and final_rect.height() > 10:
                cropped = self.original_pixmap.copy(final_rect)
                if self.parent():
                    self.parent().on_capture_completed(cropped, final_rect)

# --- 메인 컨트롤 패널 ---
class CaptureTool(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("악보 수집 도구 🎵")
        self.setWindowFlags(Qt.WindowStaysOnTopHint)
        
        # [설정] 드래그 앤 드롭 활성화
        self.setAcceptDrops(True) 
        self.is_drag_active = False # 드래그 시각 효과를 위한 플래그

        if getattr(sys, 'frozen', False):
            self.app_dir = os.path.dirname(sys.executable)
        else:
            self.app_dir = os.path.dirname(os.path.abspath(__file__))

        # 아이콘 설정
        icon_path = os.path.join(self.app_dir, "capture_icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.save_dir = load_settings(self.app_dir)
        self.is_stitch_mode = False 
        self.stitch_buffer = [] 
        self.master_rect_info = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(12)  # 위젯 간 간격 조정

        # --- [수정] 사용 설명 가이드 영역 ---
        guide_frame = QFrame()
        guide_frame.setFrameShape(QFrame.StyledPanel)
        guide_frame.setStyleSheet("""
            QFrame {
                background-color: #f2f9ff;
                border: 1px solid #cce5ff;
                border-radius: 8px;
            }
        """)
        guide_layout = QVBoxLayout(guide_frame)
        guide_layout.setContentsMargins(10, 10, 10, 10)

        # HTML을 사용하여 3가지 핵심 기능 설명
        guide_text = (
            "<div style='line-height: 140%; font-size: 10pt; color: #333;'>"
            "<b>📌 간편 사용 가이드</b>"
            "<ul style='margin-left: -15px; margin-top: 5px;'>"
            "<li><b>드래그 & 드롭:</b> <span style='color:#0056b3;'>웹 상의 악보 이미지</span>나 파일을 이 창에 끌어 놓으세요.</li>"
            "<li><b>클라우드 동기화:</b> 저장 시 <span style='color:#0056b3;'>구글 드라이브</span>에 자동 업로드됩니다.</li>"
            "<li><b>긴 악보 캡처:</b> 스크롤이 필요한 악보는 <b>[긴 악보 캡처]</b>를 눌러 나눠 찍으면 하나로 합쳐집니다.</li>"
            "</ul>"
            "</div>"
        )
        
        lbl_guide = QLabel(guide_text)
        lbl_guide.setTextFormat(Qt.RichText)
        lbl_guide.setWordWrap(True)
        guide_layout.addWidget(lbl_guide)
        layout.addWidget(guide_frame)
        # --- [끝] ---

        # 경로 및 파일명 입력 영역
        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("📂 저장 경로:"))
        self.path_input = QLineEdit(self.save_dir)
        self.path_input.setReadOnly(True)
        path_layout.addWidget(self.path_input)
        layout.addLayout(path_layout)

        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("🎵 곡 제목:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("예: 은혜 아니면 (입력 후 엔터 시 검색)")
        self.name_input.returnPressed.connect(self.search_google)
        name_layout.addWidget(self.name_input)
        
        btn_search = QPushButton("🔍 구글 검색")
        btn_search.clicked.connect(self.search_google)
        name_layout.addWidget(btn_search)
        layout.addLayout(name_layout)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        layout.addWidget(line)

        # 버튼 영역
        btn_layout = QHBoxLayout()
        self.btn_normal = QPushButton("📸 일반 캡처")
        self.btn_normal.setMinimumHeight(45)
        self.btn_normal.setCursor(Qt.PointingHandCursor)
        self.btn_normal.setStyleSheet("""
            QPushButton { 
                font-size: 11pt; font-weight: bold; 
                background-color: #0078D7; color: white; border-radius: 5px;
            }
            QPushButton:hover { background-color: #0063b1; }
        """)
        self.btn_normal.clicked.connect(self.start_normal_capture)
        btn_layout.addWidget(self.btn_normal)

        self.btn_stitch = QPushButton("📜 긴 악보 캡처")
        self.btn_stitch.setMinimumHeight(45)
        self.btn_stitch.setCursor(Qt.PointingHandCursor)
        self.btn_stitch.setStyleSheet("""
            QPushButton { 
                font-size: 11pt; font-weight: bold; 
                background-color: #6f42c1; color: white; border-radius: 5px;
            }
            QPushButton:hover { background-color: #5a32a3; }
        """)
        self.btn_stitch.clicked.connect(self.start_stitch_capture)
        btn_layout.addWidget(self.btn_stitch)
        layout.addLayout(btn_layout)

        # 긴 악보 컨트롤 (숨김 상태)
        control_layout = QHBoxLayout()
        self.btn_cancel_stitch = QPushButton("❌ 취소")
        self.btn_cancel_stitch.setMinimumHeight(40)
        self.btn_cancel_stitch.setStyleSheet("font-weight: bold; background-color: #d9534f; color: white; border-radius: 5px;")
        self.btn_cancel_stitch.clicked.connect(self.cancel_stitch)
        self.btn_cancel_stitch.hide()
        
        self.btn_save_stitch = QPushButton("💾 합치기 완료")
        self.btn_save_stitch.setMinimumHeight(40)
        self.btn_save_stitch.setStyleSheet("font-weight: bold; background-color: #28a745; color: white; border-radius: 5px;")
        self.btn_save_stitch.clicked.connect(self.save_stitched_image)
        self.btn_save_stitch.hide()
        
        control_layout.addWidget(self.btn_cancel_stitch)
        control_layout.addWidget(self.btn_save_stitch)
        layout.addLayout(control_layout)

        layout.addStretch(1)

        # 상태 표시줄
        self.status_label = QLabel("준비됨")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: gray; font-weight: bold; margin-top: 5px;")
        layout.addWidget(self.status_label)

        self.setLayout(layout)
        
        # [중요] adjustSize로 인한 깜빡임 방지를 위해 최소 크기 설정
        self.setMinimumSize(500, 380)

    # --- [효과] paintEvent: 드래그 시 오버레이 그리기 ---
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.is_drag_active:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            
            # 1. 반투명 파란색 배경
            painter.fillRect(self.rect(), QColor(0, 120, 215, 30))
            
            # 2. 점선 테두리
            pen = QPen(QColor(0, 120, 215), 3, Qt.DashLine)
            painter.setPen(pen)
            painter.drawRect(self.rect().adjusted(2, 2, -2, -2))

    # --- 드래그 앤 드롭: 로컬 파일 + 웹 이미지 지원 ---
    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasImage():
            event.acceptProposedAction()
            self.is_drag_active = True 
            self.update() 

    def dragLeaveEvent(self, event):
        self.is_drag_active = False 
        self.update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self.is_drag_active = False 
        self.update()

        mime = event.mimeData()
        pixmap = QPixmap()
        file_name_hint = "web_image" 

        try:
            if mime.hasUrls():
                url = mime.urls()[0]
                if url.isLocalFile():
                    file_path = url.toLocalFile()
                    if file_path.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')):
                        pixmap.load(file_path)
                        file_name_hint = os.path.splitext(os.path.basename(file_path))[0]
                
                elif url.scheme() in ['http', 'https']:
                    image_url = url.toString()
                    self.status_label.setText("🌐 웹 이미지 다운로드 중...")
                    QApplication.processEvents()
                    
                    response = requests.get(image_url, timeout=5)
                    if response.status_code == 200:
                        pixmap.loadFromData(response.content)
                        possible_name = os.path.basename(image_url.split('?')[0])
                        if possible_name:
                            file_name_hint = os.path.splitext(possible_name)[0]
                    else:
                        QMessageBox.warning(self, "오류", f"이미지 다운로드 실패: {response.status_code}")
                        self.status_label.setText("준비됨")
                        return

            elif mime.hasImage():
                image_data = mime.imageData()
                pixmap = QPixmap.fromImage(image_data)
                file_name_hint = "pasted_image"

            if not pixmap.isNull():
                self.name_input.setText(file_name_hint) 
                self.show_confirm_dialog(pixmap) 
                self.status_label.setText("준비됨")
            else:
                self.status_label.setText("⚠️ 이미지를 불러올 수 없습니다.")

        except Exception as e:
            QMessageBox.warning(self, "오류", f"이미지 처리 중 오류 발생: {str(e)}")
            self.status_label.setText("준비됨")

    def search_google(self):
        title = self.name_input.text().strip()
        if not title:
            QMessageBox.warning(self, "알림", "곡 제목을 입력해주세요.")
            return
        query = urllib.parse.quote_plus(f"{title} 악보")
        url = f"https://www.google.com/search?tbm=isch&q={query}"
        webbrowser.open(url)
        self.status_label.setText(f"'{title}' 검색 중...")

    def start_normal_capture(self):
        self.is_stitch_mode = False
        self.reset_buffer()
        self.launch_capture_sequence()
    def start_stitch_capture(self):
        self.is_stitch_mode = True
        if self.stitch_buffer:
            self.launch_capture_sequence()
        else:
            self.reset_buffer()
            self.launch_capture_sequence()
    def launch_capture_sequence(self):
        self.showMinimized()
        QTimer.singleShot(200, self.launch_snipping_tool)
    def launch_snipping_tool(self):
        rect_to_pass = None
        prev_img_to_pass = None
        if self.is_stitch_mode and self.master_rect_info:
            rect_to_pass = self.master_rect_info
            if self.stitch_buffer:
                prev_img_to_pass = self.stitch_buffer[-1]
        self.snipper = SnippingWidget(self, master_rect=rect_to_pass, prev_pixmap=prev_img_to_pass)
        self.snipper.show()
        self.snipper.activateWindow()
        self.snipper.raise_()
    def on_capture_completed(self, pixmap, rect):
        self.showNormal()
        self.activateWindow()
        if self.is_stitch_mode:
            if not self.stitch_buffer:
                self.master_rect_info = rect 
            self.stitch_buffer.append(pixmap)
            count = len(self.stitch_buffer)
            self.btn_normal.hide() 
            self.btn_stitch.setText("📸 다음 부분 캡처 (계속)") 
            self.btn_stitch.setStyleSheet("font-size: 12pt; font-weight: bold; background-color: #ff9800; color: white; border-radius: 5px;")
            self.btn_cancel_stitch.show()
            self.btn_save_stitch.show()
            
            # [수정] 크기 자동 조절 제거 (깜빡임 방지)
            # self.adjustSize()
            
            self.btn_save_stitch.setText(f"💾 합치기 완료 ({count}개)")
            if count == 1:
                self.status_label.setText("1번 완료. 스크롤 후 [다음 부분 캡처]를 누르세요.")
            else:
                self.status_label.setText(f"{count}번 완료. 계속 찍거나 [완료]를 누르세요.")
            self.status_label.setStyleSheet("color: blue; font-weight: bold;")
        else:
            self.show_confirm_dialog(pixmap)
    def show_confirm_dialog(self, pixmap):
        current_name = self.name_input.text().strip()
        dialog = ConfirmDialog(pixmap, current_name, self.save_dir, self)
        if dialog.exec() == QDialog.Accepted:
            target_dir, new_name, do_upload = dialog.get_data()
            if not new_name:
                QMessageBox.warning(self, "오류", "파일명을 입력해야 합니다.")
                return 
            self.name_input.setText(new_name)
            if target_dir != self.save_dir:
                self.save_dir = target_dir
                self.path_input.setText(self.save_dir)
            self.save_final_image(pixmap, new_name, target_dir, do_upload)
    def save_final_image(self, pixmap, filename_no_ext, target_dir, do_upload):
        filename = f"{filename_no_ext}.jpg"
        if not target_dir:
            target_dir = self.save_dir
        full_path = os.path.join(target_dir, filename)
        if os.path.exists(full_path):
            reply = QMessageBox.question(self, "덮어쓰기 확인", f"'{filename}' 파일이 이미 존재합니다. 덮어쓰시겠습니까?", QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.No:
                return
        try:
            pixmap.save(full_path, "JPG")
            self.status_label.setText(f"✅ 저장 완료: {filename}")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
            if self.is_stitch_mode:
                self.reset_ui_to_initial()
            if do_upload:
                self.start_upload_to_drive(pixmap, filename)
        except Exception as e:
            QMessageBox.critical(self, "오류", f"저장 실패: {e}")

    # HTTP POST 방식으로 업로드
    def start_upload_to_drive(self, pixmap, file_name):
        if not GOOGLE_SCRIPT_URL.startswith("https://script.google.com"):
            QMessageBox.warning(self, "설정 필요", "코드 상단의 GOOGLE_SCRIPT_URL을 설정해주세요.")
            return

        self.status_label.setText(f"☁️ 웹으로 전송 중... ({file_name})")
        self.status_label.setStyleSheet("color: blue; font-weight: bold;")
        
        self.upload_thread = UploadThread(GOOGLE_SCRIPT_URL, pixmap, file_name)
        self.upload_thread.finished_signal.connect(self.on_upload_finished)
        self.upload_thread.start()

    def on_upload_finished(self, success, msg):
        if success:
            self.status_label.setText(msg)
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.status_label.setText("❌ 업로드 실패")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            QMessageBox.warning(self, "업로드 실패", msg)

    def save_stitched_image(self):
        if not self.stitch_buffer:
            return
        try:
            max_width = 0
            total_height = 0
            for p in self.stitch_buffer:
                if p.width() > max_width:
                    max_width = p.width()
                total_height += p.height()
            combined_pixmap = QPixmap(max_width, total_height)
            combined_pixmap.fill(Qt.white)
            painter = QPainter(combined_pixmap)
            current_y = 0
            for p in self.stitch_buffer:
                painter.drawPixmap(0, current_y, p)
                current_y += p.height()
            painter.end()
            self.show_confirm_dialog(combined_pixmap)
        except Exception as e:
            QMessageBox.critical(self, "오류", f"합치기 처리 실패: {e}")
    def cancel_stitch(self):
        self.reset_ui_to_initial()
        self.status_label.setText("작업이 취소되었습니다.")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
    def reset_buffer(self):
        self.stitch_buffer = []
        self.master_rect_info = None
    def reset_ui_to_initial(self):
        self.reset_buffer()
        self.is_stitch_mode = False
        self.btn_normal.show()
        self.btn_stitch.setText("📜 긴 악보 캡처")
        self.btn_stitch.setStyleSheet("""
            QPushButton { 
                font-size: 11pt; font-weight: bold; 
                background-color: #6f42c1; color: white; border-radius: 5px;
            }
            QPushButton:hover { background-color: #5a32a3; }
        """)
        self.btn_cancel_stitch.hide()
        self.btn_save_stitch.hide()
        self.status_label.setText("준비됨")
        self.status_label.setStyleSheet("color: gray; font-weight: bold;")
        
        # [수정] 크기 자동 조절 제거
        # self.adjustSize()

if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        window = CaptureTool()
        window.show()
        window.activateWindow()
        window.raise_()
        sys.exit(app.exec())
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        print(f"\n실행 중 오류 발생: {e}")
        sys.exit(1)