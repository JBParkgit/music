import sys
import json
import os
import re
import csv
from datetime import datetime
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
    QGraphicsDropShadowEffect,
    QFrame,
    QFontComboBox,
    QToolButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSpinBox,
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
            # 이름 열(0)만 커스텀 표시, 나머지(크기/유형/날짜)는 소스 모델 값 사용
            if index.column() != 0:
                return super().data(index, role)
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

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        """날짜 열(3) 정렬 시 파일 수정 시간 기준으로 비교합니다."""
        source_model = self.sourceModel()

        # 날짜 컬럼(3)일 때는 파일의 수정 시간을 기준으로 비교
        if left.column() == 3 and right.column() == 3:
            try:
                left_index0 = source_model.index(left.row(), 0, left.parent())
                right_index0 = source_model.index(right.row(), 0, right.parent())
                path_left = source_model.filePath(left_index0)
                path_right = source_model.filePath(right_index0)
                t_left = os.path.getmtime(path_left) if os.path.exists(path_left) else 0
                t_right = os.path.getmtime(path_right) if os.path.exists(path_right) else 0
                return t_left < t_right  # 오름차순 기준, 내림차순은 프록시가 자동 반전
            except (OSError, TypeError):
                pass

        return super().lessThan(left, right)

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

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            headers = ["이름", "크기", "유형", "날짜"]
            if 0 <= section < len(headers):
                return headers[section]
        return super().headerData(section, orientation, role)

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

    def find_file_in_folder_by_name(self, file_name: str):
        """지정한 Drive 폴더( drive_folder_id ) 안에서 파일명을 기준으로 파일 1개를 찾습니다."""
        if not self.service:
            return None
        query = f"'{self.drive_folder_id}' in parents and trashed=false and name='{file_name}'"
        results = (
            self.service.files()
            .list(q=query, pageSize=5, fields="files(id, name, mimeType, modifiedTime)")
            .execute()
        )
        files = results.get("files", [])
        return files[0] if files else None

    def download_named_file(self, file_name: str, local_path: str) -> bool:
        """Drive 폴더에서 file_name 파일을 찾아 local_path로 다운로드합니다."""
        item = self.find_file_in_folder_by_name(file_name)
        if not item:
            return False
        # Google 스프레드시트인 경우 CSV로 내보내기(export) 필요
        mime_type = item.get("mimeType", "")
        if mime_type == "application/vnd.google-apps.spreadsheet":
            self._export_spreadsheet_as_csv(item["id"], local_path)
        else:
            self._download_file(item["id"], local_path)
        return True

    def _export_spreadsheet_as_csv(self, file_id: str, file_path: str):
        request = self.service.files().export_media(fileId=file_id, mimeType="text/csv")
        with open(file_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()

    def _download_file(self, file_id, file_path):
        request = self.service.files().get_media(fileId=file_id)
        with open(file_path, "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                status, done = downloader.next_chunk()


# --- [Google Drive + Sheets(쓰기) 연동] ---
class GoogleWorkspaceSync:
    """Drive(목록/내보내기) + Sheets(행 업데이트/추가) 동시 사용을 위한 헬퍼"""

    def __init__(self, service_account_file, drive_folder_id, app_dir):
        self.SCOPES = [
            "https://www.googleapis.com/auth/drive.readonly",
            "https://www.googleapis.com/auth/spreadsheets",
        ]
        self.service_account_file = service_account_file
        self.drive_folder_id = drive_folder_id
        self.app_dir = app_dir
        self.drive = None
        self.sheets = None

    def connect(self):
        if not GOOGLE_LIB_AVAILABLE:
            return False
        try:
            creds = service_account.Credentials.from_service_account_file(
                self.service_account_file, scopes=self.SCOPES
            )
            self.drive = build("drive", "v3", credentials=creds)
            self.sheets = build("sheets", "v4", credentials=creds)
            return True
        except Exception as e:
            print(f"연결 실패: {e}")
            return False

    def find_file_in_folder_by_name(self, file_name: str):
        if not self.drive:
            return None
        query = f"'{self.drive_folder_id}' in parents and trashed=false and name='{file_name}'"
        results = (
            self.drive.files()
            .list(q=query, pageSize=5, fields="files(id, name, mimeType, modifiedTime)")
            .execute()
        )
        files = results.get("files", [])
        return files[0] if files else None

    def get_first_sheet_title(self, spreadsheet_id: str) -> str:
        meta = self.sheets.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = meta.get("sheets", [])
        if not sheets:
            return "Sheet1"
        props = sheets[0].get("properties", {})
        return props.get("title", "Sheet1")


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
    finished_signal = Signal(bool, int, str)  # db_updated 인자 제거

    def __init__(self, sync_helper):
        super().__init__()
        self.sync_helper = sync_helper

    def run(self):
        try:
            self.log_signal.emit("Google Drive에 연결 중...")
            if not self.sync_helper.connect():
                self.finished_signal.emit(
                    False, 0, "구글 인증 실패: service_account.json 확인"
                )
                return

            self.log_signal.emit("전체 파일 목록을 받아오는 중...")
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

                items.extend(results.get("files", []))
                page_token = results.get("nextPageToken")
                if not page_token:
                    break

            download_list = []
            # DB 파일(song_metadata.db) 관련 로직 삭제됨
            for item in items:
                if "application/vnd.google-apps" in item["mimeType"]:
                    continue

                file_name = item["name"]
                # DB 파일은 동기화 대상에서 제외 (별도 버튼으로 관리)
                if file_name == "song_metadata.db":
                    continue

                local_path = os.path.join(self.sync_helper.local_dir, file_name)
                if not os.path.exists(local_path):
                    download_list.append(item)

            total_actions = len(download_list)
            download_count = 0

            for item in download_list:
                download_count += 1
                file_name = item["name"]
                local_path = os.path.join(self.sync_helper.local_dir, file_name)

                self.log_signal.emit(f"[다운로드] {file_name}")
                self.progress_signal.emit(download_count, total_actions)

                try:
                    self.sync_helper._download_file(item["id"], local_path)
                except Exception as e:
                    self.log_signal.emit(f"❌ 실패: {file_name} - {e}")

            final_msg = "악보 파일 동기화가 완료되었습니다."
            if download_count == 0:
                final_msg = f"총 {len(items)}개 파일 확인됨. (새로운 악보 없음)"

            self.finished_signal.emit(True, download_count, final_msg)

        except Exception as e:
            self.finished_signal.emit(False, 0, f"오류 발생: {str(e)}")


# --- [메타데이터(DB) 동기화 스레드] ---
class MetadataSyncThread(QThread):
    """Drive에 있는 song_metadata.csv(기본값)를 내려받아 로컬 SQLite DB를 갱신합니다."""

    log_signal = Signal(str)
    finished_signal = Signal(bool, int, str)

    def __init__(self, sync_helper, csv_name, db_path, sheet_music_path):
        super().__init__()
        self.sync_helper = sync_helper
        self.csv_name = csv_name
        self.db_path = db_path
        self.sheet_music_path = sheet_music_path

    def _ensure_db_columns(self, con: sqlite3.Connection):
        """기존 DB가 있을 때 컬럼이 부족하면 안전하게 추가합니다."""
        cur = con.cursor()
        cur.execute("PRAGMA table_info(song_metadata)")
        cols = {row[1] for row in cur.fetchall()}
        if "updated_at" not in cols:
            cur.execute("ALTER TABLE song_metadata ADD COLUMN updated_at TEXT")
        if "updated_by" not in cols:
            cur.execute("ALTER TABLE song_metadata ADD COLUMN updated_by TEXT")
        if "dirty" not in cols:
            cur.execute("ALTER TABLE song_metadata ADD COLUMN dirty INTEGER DEFAULT 0")
        con.commit()

    def _to_abs_path(self, raw_path: str) -> str:
        if not raw_path:
            return ""
        p = raw_path.strip().replace("/", os.sep)
        # 이미 절대경로(윈도우 드라이브/UNC)라면 그대로
        if os.path.isabs(p):
            return os.path.normpath(p)
        # 상대경로라면 악보 폴더 기준으로 합치기
        return os.path.normpath(os.path.join(self.sheet_music_path, p))

    def run(self):
        try:
            self.log_signal.emit("Google Drive에 연결 중...")
            if not self.sync_helper.connect():
                self.finished_signal.emit(
                    False, 0, "구글 인증 실패: service_account.json 확인"
                )
                return

            # 1) CSV 다운로드
            self.log_signal.emit(f"메타데이터 파일 찾는 중: {self.csv_name}")
            local_csv_path = os.path.join(self.sync_helper.app_dir, self.csv_name)
            ok = self.sync_helper.download_named_file(self.csv_name, local_csv_path)
            if not ok:
                self.finished_signal.emit(
                    False,
                    0,
                    f"Drive 폴더에서 '{self.csv_name}' 파일을 찾을 수 없습니다. (파일명 확인)",
                )
                return

            self.log_signal.emit(f"다운로드 완료: {local_csv_path}")

            # 2) CSV 파싱 & DB 반영
            updated_rows = 0
            con = sqlite3.connect(self.db_path)
            cur = con.cursor()

            # 테이블이 없다면 생성(기존 init_database와 동일한 기본 구조 + 확장 컬럼)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS song_metadata (
                    file_path TEXT PRIMARY KEY,
                    song_key TEXT,
                    lyrics TEXT,
                    updated_at TEXT,
                    updated_by TEXT,
                    dirty INTEGER DEFAULT 0
                )
                """
            )
            con.commit()

            # 기존 DB에 컬럼이 없을 수 있어 안전하게 보강
            self._ensure_db_columns(con)

            with open(local_csv_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                # 필수 컬럼 체크(느슨하게 허용)
                fieldnames = {c.strip() for c in (reader.fieldnames or [])}
                if "file_path" not in fieldnames:
                    self.finished_signal.emit(
                        False, 0, "CSV에 'file_path' 컬럼이 없습니다."
                    )
                    con.close()
                    return

                batch = []
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                for row in reader:
                    raw_path = (row.get("file_path") or "").strip()
                    if not raw_path:
                        continue
                    abs_path = self._to_abs_path(raw_path)

                    song_key = (row.get("song_key") or "").strip()
                    lyrics = (row.get("lyrics") or "").strip()
                    updated_at = (row.get("updated_at") or "").strip() or now
                    updated_by = (row.get("updated_by") or "").strip()

                    batch.append((abs_path, song_key, lyrics, updated_at, updated_by))
                if batch:
                    # dirty 여부와 관계없이 항상 온라인 CSV 기준으로 덮어씁니다.
                    for rec in batch:
                        cur.execute(
                            """
                            INSERT INTO song_metadata (file_path, song_key, lyrics, updated_at, updated_by, dirty)
                            VALUES (?, ?, ?, ?, ?, 0)
                            ON CONFLICT(file_path) DO UPDATE SET
                                song_key=excluded.song_key,
                                lyrics=excluded.lyrics,
                                updated_at=excluded.updated_at,
                                updated_by=excluded.updated_by,
                                dirty=0
                            """,
                            rec,
                        )
                    con.commit()
                    updated_rows = len(batch)

            con.close()

            self.finished_signal.emit(
                True, updated_rows, f"DB 동기화 완료: {updated_rows}건 반영"
            )

        except Exception as e:
            self.finished_signal.emit(False, 0, f"DB 동기화 오류: {str(e)}")


# --- [로컬 -> 중앙(스프레드시트) 업로드 스레드] ---
class MetadataUploadThread(QThread):
    """로컬 DB에서 dirty=1 인 항목을 중앙 스프레드시트에 upsert(행 업데이트/추가)합니다."""

    log_signal = Signal(str)
    finished_signal = Signal(bool, int, str)

    def __init__(
        self,
        ws_helper: GoogleWorkspaceSync,
        sheet_name: str,
        db_path: str,
        sheet_music_path: str,
        editor_name: str,
    ):
        super().__init__()
        self.ws_helper = ws_helper
        self.sheet_name = sheet_name
        self.db_path = db_path
        self.sheet_music_path = sheet_music_path
        self.editor_name = editor_name or ""

    def _ensure_db_columns(self, con: sqlite3.Connection):
        cur = con.cursor()
        cur.execute("PRAGMA table_info(song_metadata)")
        cols = {row[1] for row in cur.fetchall()}
        if "updated_at" not in cols:
            cur.execute("ALTER TABLE song_metadata ADD COLUMN updated_at TEXT")
        if "updated_by" not in cols:
            cur.execute("ALTER TABLE song_metadata ADD COLUMN updated_by TEXT")
        if "dirty" not in cols:
            cur.execute("ALTER TABLE song_metadata ADD COLUMN dirty INTEGER DEFAULT 0")
        con.commit()

    def _to_rel_path(self, abs_path: str) -> str:
        if not abs_path:
            return ""
        try:
            base = os.path.normpath(self.sheet_music_path)
            p = os.path.normpath(abs_path)
            if p.lower().startswith(base.lower()):
                rel = os.path.relpath(p, base)
            else:
                rel = p
            return rel.replace(os.sep, "/")
        except Exception:
            return abs_path.replace(os.sep, "/")

    def run(self):
        con = None
        try:
            self.log_signal.emit("Google Drive/Sheets 연결 중...")
            if not self.ws_helper.connect():
                self.finished_signal.emit(
                    False, 0, "구글 인증 실패: service_account.json 확인"
                )
                return

            self.log_signal.emit(f"중앙 스프레드시트 찾는 중: {self.sheet_name}")
            item = self.ws_helper.find_file_in_folder_by_name(self.sheet_name)
            if not item:
                self.finished_signal.emit(
                    False,
                    0,
                    f"Drive 폴더에서 '{self.sheet_name}' 파일을 찾을 수 없습니다.",
                )
                return

            mime = item.get("mimeType", "")
            if mime != "application/vnd.google-apps.spreadsheet":
                self.finished_signal.emit(
                    False,
                    0,
                    f"'{self.sheet_name}' 파일이 스프레드시트가 아닙니다. (mimeType={mime})",
                )
                return

            spreadsheet_id = item["id"]
            tab_title = self.ws_helper.get_first_sheet_title(spreadsheet_id)

            con = sqlite3.connect(self.db_path)
            cur = con.cursor()

            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS song_metadata (
                    file_path TEXT PRIMARY KEY,
                    song_key TEXT,
                    lyrics TEXT,
                    updated_at TEXT,
                    updated_by TEXT,
                    dirty INTEGER DEFAULT 0
                )
                """
            )
            con.commit()
            self._ensure_db_columns(con)

            cur.execute(
                """
                SELECT file_path, song_key, lyrics, COALESCE(updated_at,''), COALESCE(updated_by,'')
                FROM song_metadata
                WHERE COALESCE(dirty,0)=1
                """
            )
            local_rows = cur.fetchall()
            if not local_rows:
                self.finished_signal.emit(
                    True, 0, "업로드할 변경사항이 없습니다. (dirty=1 항목 없음)"
                )
                con.close()
                return

            self.log_signal.emit("중앙 시트 읽는 중(기존 데이터 확인)...")
            header = ["file_path", "song_key", "lyrics", "updated_at", "updated_by"]
            rng = f"{tab_title}!A:E"
            resp = (
                self.ws_helper.sheets.spreadsheets()
                .values()
                .get(spreadsheetId=spreadsheet_id, range=rng)
                .execute()
            )
            values = resp.get("values", [])

            if not values:
                self.log_signal.emit("중앙 시트가 비어있어 헤더를 생성합니다.")
                self.ws_helper.sheets.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=f"{tab_title}!A1:E1",
                    valueInputOption="RAW",
                    body={"values": [header]},
                ).execute()
                values = [header]

            existing_map = {}
            for idx_row, r in enumerate(values[1:], start=2):
                if len(r) >= 1 and str(r[0]).strip():
                    existing_map[str(r[0]).strip()] = idx_row

            updates = []
            appends = []
            changed_abs_paths = []
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            for abs_path, song_key, lyrics, updated_at, updated_by in local_rows:
                rel_path = self._to_rel_path(abs_path)
                up_at = (updated_at or "").strip() or now
                up_by = (updated_by or "").strip() or self.editor_name
                record = [
                    rel_path,
                    (song_key or "").strip(),
                    (lyrics or "").strip(),
                    up_at,
                    up_by,
                ]

                if rel_path in existing_map:
                    row_no = existing_map[rel_path]
                    updates.append((row_no, record))
                else:
                    appends.append(record)

                changed_abs_paths.append(abs_path)

            written = 0
            if updates:
                self.log_signal.emit(f"중앙 시트 업데이트: {len(updates)}건")
                data = [
                    {"range": f"{tab_title}!A{row_no}:E{row_no}", "values": [record]}
                    for row_no, record in updates
                ]
                self.ws_helper.sheets.spreadsheets().values().batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body={"valueInputOption": "RAW", "data": data},
                ).execute()
                written += len(updates)

            if appends:
                self.log_signal.emit(f"중앙 시트 추가: {len(appends)}건")
                self.ws_helper.sheets.spreadsheets().values().append(
                    spreadsheetId=spreadsheet_id,
                    range=f"{tab_title}!A:E",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": appends},
                ).execute()
                written += len(appends)

            self.log_signal.emit("로컬 DB 상태 업데이트(dirty=0)...")
            cur.executemany(
                "UPDATE song_metadata SET dirty=0 WHERE file_path=?",
                [(p,) for p in changed_abs_paths],
            )
            con.commit()
            con.close()

            self.finished_signal.emit(
                True, written, f"중앙 업로드 완료: {written}건 반영"
            )

        except Exception as e:
            try:
                if con:
                    con.close()
            except Exception:
                pass
            self.finished_signal.emit(False, 0, f"중앙 업로드 오류: {str(e)}")


# --- [추가] 텍스트 슬라이드 입력 다이얼로그 ---

class TextSlideDialog(QDialog):
    def __init__(self, parent=None, initial_data=None):
        super().__init__(parent)
        self.setWindowTitle("텍스트 슬라이드 추가")
        self.resize(1000, 700) 
        
        main_layout = QHBoxLayout(self)
        
        # === 좌측 패널 (입력 및 설정) ===
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        # 1. 텍스트 입력 영역
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("성경 구절이나 문구를 입력하세요...\n(예: 하나님은 사랑이시라)")
        self.text_edit.textChanged.connect(self.update_preview)
        
        # 2. 테마 선택
        grid_layout = QFormLayout()

        self.theme_combo = QComboBox()
        self.theme_combo.addItems([
            "말씀 (Warm Paper)",
            "기본 (Deep Black)", 
            "새벽 (Midnight Blue)", 
            "은혜 (Graceful Purple)"
        ])
        self.theme_combo.currentTextChanged.connect(self.update_preview)
        grid_layout.addRow("🎨 테마:", self.theme_combo)

        # 3. 폰트 설정 (폰트, 크기, 증감 버튼)
        font_box = QHBoxLayout()
        
        # 폰트 패밀리
        self.font_combo = QFontComboBox()
        self.font_combo.setFontFilters(QFontComboBox.ScalableFonts)
        self.font_combo.setEditable(False)
        self.font_combo.setCurrentFont(QFont("맑은 고딕")) 
        self.font_combo.currentFontChanged.connect(self.update_preview)
        font_box.addWidget(self.font_combo, 2)

        # 폰트 크기
        self.size_combo = QComboBox()
        self.size_combo.setEditable(True)
        # 워드 프로세서 표준 크기 목록
        self.standard_sizes = [
            8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 
            36, 48, 60, 72, 80, 96, 120, 150, 200
        ]
        self.size_combo.addItems([str(s) for s in self.standard_sizes])
        
        # 기본값 50
        self.size_combo.setCurrentText("50")
        
        self.size_combo.editTextChanged.connect(self.update_preview)
        self.size_combo.currentIndexChanged.connect(self.update_preview)
        
        font_box.addWidget(self.size_combo, 1)

        # 크기 조절 버튼
        self.btn_size_up = QToolButton()
        self.btn_size_up.setText("가+") 
        self.btn_size_up.setToolTip("글자 크게")
        self.btn_size_up.clicked.connect(lambda: self.adjust_font_size(1))
        
        self.btn_size_down = QToolButton()
        self.btn_size_down.setText("가-")
        self.btn_size_down.setToolTip("글자 작게")
        self.btn_size_down.clicked.connect(lambda: self.adjust_font_size(-1))

        font_box.addWidget(self.btn_size_up)
        font_box.addWidget(self.btn_size_down)

        grid_layout.addRow("🔤 폰트:", font_box)
        
        # 4. 버튼
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        
        left_layout.addWidget(QLabel("📝 내용 입력:"))
        left_layout.addWidget(self.text_edit, 1)
        left_layout.addLayout(grid_layout)
        left_layout.addWidget(button_box)
        
        # === 우측 패널 (미리보기) ===
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        preview_group = QGroupBox("미리보기")
        preview_inner_layout = QVBoxLayout(preview_group)
        
        # 16:9 비율 유지 프레임 (배경) -> 1920x1080의 1/3 = 640x360
        self.preview_frame = QFrame()
        self.preview_frame.setFixedSize(640, 360) 
        self.preview_frame.setFrameShape(QFrame.NoFrame)
        
        # 카드 프레임 (내용물)
        target_preview_width = 512 
        
        self.card_frame = QFrame(self.preview_frame)
        self.card_frame.setFixedWidth(target_preview_width)
        
        frame_layout = QVBoxLayout(self.preview_frame)
        frame_layout.addWidget(self.card_frame, 0, Qt.AlignCenter)
        frame_layout.setContentsMargins(0,0,0,0)
        
        self.card_frame.setStyleSheet("background-color: transparent;")
        
        # 그림자 효과
        self.shadow_effect = QGraphicsDropShadowEffect()
        self.shadow_effect.setBlurRadius(20) 
        self.shadow_effect.setColor(QColor(0, 0, 0, 50))
        self.shadow_effect.setOffset(0, 2)
        self.card_frame.setGraphicsEffect(self.shadow_effect)
        
        self.preview_label = QLabel(self.card_frame)
        self.preview_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.preview_label.setWordWrap(True)
        
        card_layout = QVBoxLayout(self.card_frame)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.addWidget(self.preview_label)

        preview_inner_layout.addWidget(self.preview_frame, 0, Qt.AlignCenter)
        right_layout.addWidget(preview_group)
        
        main_layout.addWidget(left_panel, 1)
        main_layout.addWidget(right_panel, 2)

        # [추가] 초기 데이터가 있으면 설정
        if initial_data:
             self.setWindowTitle("텍스트 슬라이드 수정")
             self.text_edit.setPlainText(initial_data.get("text", ""))
             self.theme_combo.setCurrentText(initial_data.get("theme", "말씀 (Warm Paper)"))
             
             f_size = initial_data.get("font_size", 50)
             self.size_combo.setCurrentText(str(f_size))
             
             if "font_family" in initial_data:
                 self.font_combo.setCurrentFont(QFont(initial_data["font_family"]))
        
        self.update_preview()

    def adjust_font_size(self, direction):
        try:
            current_val = float(self.size_combo.currentText())
        except ValueError:
            current_val = 50.0

        import bisect
        sorted_sizes = sorted(self.standard_sizes)
        
        idx = bisect.bisect_right(sorted_sizes, current_val)
        
        new_val = current_val
        if direction > 0:
            if idx < len(sorted_sizes):
                new_val = sorted_sizes[idx]
            else:
                new_val = current_val + 5
        else:
            smaller = [s for s in sorted_sizes if s < current_val]
            if smaller:
                new_val = smaller[-1]
            else:
                new_val = max(5, current_val - 5)
        
        self.size_combo.setCurrentText(str(int(new_val)))

    def get_data(self):
        try:
            f_size = int(float(self.size_combo.currentText()))
        except:
            f_size = 50
            
        return {
            "text": self.text_edit.toPlainText().strip(),
            "theme": self.theme_combo.currentText(),
            "font_size": f_size,
            "font_family": self.font_combo.currentFont().family()
        }

    def update_preview(self, *args):
        text = self.text_edit.toPlainText() or "미리보기 텍스트"
        theme = self.theme_combo.currentText()
        
        try:
            font_size = float(self.size_combo.currentText())
        except ValueError:
            font_size = 50.0
            
        font_family = self.font_combo.currentFont().family()
        
        # 미리보기용 폰트 크기 조정 (정확히 1/3 비율)
        scale_factor = 1/3
        preview_font_size = max(5, int(font_size * scale_factor))
        
        self.preview_label.setText(text)
        
        style = self.get_theme_style(theme)
        
        # 1. 전체 배경
        self.preview_frame.setStyleSheet(f"""
            QFrame {{
                {style['bg']}
            }}
        """)
        
        # 2. 카드 스타일
        card_bg = "background-color: rgba(255, 255, 255, 0.9);"
        border_style = "border: 1px solid #d0d0d0;"
        radius = "border-radius: 6px;" 
        
        if "Deep Black" in theme or "Midnight" in theme:
             card_bg = "background-color: rgba(0, 0, 0, 0.4);"
             border_style = "border: 1px solid rgba(255, 255, 255, 0.2);"
        
        self.card_frame.setStyleSheet(f"""
            QFrame {{
                {card_bg}
                {border_style}
                {radius}
            }}
        """)
        
        # 3. 텍스트 스타일: 폰트 적용
        padding_val = int(60 * scale_factor)
        margin_val = int(50 * scale_factor)
        
        self.preview_label.setStyleSheet(f"""
            QLabel {{
                color: {style['color']};
                font-family: '{font_family}';
                font-size: {preview_font_size}pt;
                font-weight: bold;
                background-color: transparent;
                border: none;
                padding: {padding_val}px; 
            }}
        """)
        
        target_height = 360 - (margin_val * 2)
        self.card_frame.setFixedHeight(target_height)
        self.preview_frame.layout().setContentsMargins(0, margin_val, 0, margin_val)

    def get_theme_style(self, theme_name):
        # 테마별 CSS 정의 (배경 및 글자색)
        if "새벽" in theme_name:
            # Midnight Blue Gradient
            return {
                "bg": "background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0f2027, stop:1 #203a43);",
                "color": "#ffffff"
            }
        elif "말씀" in theme_name:
            # Warm Paper / Brown Gradient
            return {
                "bg": "background-color: #f5f5f0;", # Matte paper color
                "color": "#333333" 
            }
        elif "은혜" in theme_name:
            # Soft Purple Gradient
            return {
                "bg": "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #23074d, stop:1 #cc5333);",
                "color": "#333333"
            }
        else: # 기본 (Deep Black)
            return {
                "bg": "background-color: #000000;",
                "color": "#ffffff"
            }

class PraiseSheetViewer(QMainWindow):

    # --- [헬퍼 메서드 수정] ---
    def set_icon_button(self, btn: QPushButton, icon_std, tooltip: str, text: str = ""):
        """
        버튼에 아이콘과 텍스트를 함께 설정합니다.
        텍스트가 있으면 아이콘 옆에 표시되고, 없으면 아이콘만 표시됩니다.
        """
        if isinstance(icon_std, str):
            # 문자열(이모지 등)인 경우
            btn.setText(f"{icon_std} {text}".strip())
        else:
            # QStyle StandardIcon인 경우
            btn.setIcon(self.style().standardIcon(icon_std))
            btn.setText(text)

        btn.setToolTip(tooltip)

        # 텍스트가 없으면 버튼을 정사각형으로 만듦
        if not text:
            btn.setFixedWidth(40)
        else:
            # 텍스트가 있으면 여백을 포함하여 크기 자동 조절
            btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
            btn.setContentsMargins(5, 0, 5, 0)

    # --- [__init__ 메서드 수정: 초기 크기 지정] ---
    def __init__(self):
        super().__init__()
        self.setWindowTitle("물댄동산 악보 뷰어 Pet1 2:9 V4.1")

        # 초기 크기를 넉넉히 잡아 윈도우 매니저가 배치할 때 깜빡임 최소화
        self.resize(1600, 900)

        # --- [최적화] 폰트 워밍업 ---
        self.font_warmer = QLabel("⭐ 🎼", self)
        self.font_warmer.setGeometry(-100, -100, 10, 10)

        self.viewer = None
        self.current_tooltip_index = QModelIndex()
        self.current_playlist_tooltip_item = None
        self.current_list_tooltip_item = None
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

        # =========================================================
        # [UI 구성 시작]
        # =========================================================

        # --- 1. 폴더 경로 설정 UI (설정창용) ---
        self.path_label = QLineEdit(os.path.normpath(self.sheet_music_path))
        self.path_label.setReadOnly(True)
        self.btn_change_folder = QPushButton("변경")
        self.btn_change_folder.clicked.connect(self.change_sheet_music_folder)

        self.playlist_path_label = QLineEdit(os.path.normpath(self.playlist_path))
        self.playlist_path_label.setReadOnly(True)
        self.btn_change_playlist_folder = QPushButton("변경")
        self.btn_change_playlist_folder.clicked.connect(self.change_playlist_folder)

        # --- 2. 트리 뷰 설정 ---
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
        # 이름 + 날짜만 보이도록 설정
        self.playlist_tree.setColumnHidden(1, True)  # Size
        self.playlist_tree.setColumnHidden(2, True)  # Type
        self.playlist_tree.setColumnHidden(3, False)  # Date
        header = self.playlist_tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.playlist_tree.setSortingEnabled(True)
        self.playlist_tree.sortByColumn(0, Qt.AscendingOrder)
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



        # --- 3. 검색 및 필터 UI ---
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(300)
        self.search_timer.timeout.connect(self.perform_search_filter)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 악보 검색...")
        self.search_input.textChanged.connect(self.on_search_text_changed)

        self.search_type_combo = QComboBox()
        self.search_type_combo.addItems(["파일이름", "가사"])
        self.search_type_combo.setFixedWidth(120)

        self.btn_reset_search = QPushButton()
        self.set_icon_button(
            self.btn_reset_search, QStyle.SP_DialogResetButton, "검색 초기화"
        )
        self.btn_reset_search.clicked.connect(self.reset_search_filter)

        search_layout = QHBoxLayout()
        search_layout.addWidget(self.search_type_combo)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.btn_reset_search)

        self.sheet_sort_combo = QComboBox()
        self.sheet_sort_combo.addItems(["이름 ▲", "이름 ▼", "Key ▲", "Key ▼"])
        self.sheet_sort_combo.setFixedWidth(80)
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
        self.key_filter_combo.setFixedWidth(70)
        self.key_filter_combo.currentTextChanged.connect(self.on_key_filter_changed)

        sheet_controls_layout = QHBoxLayout()

        # [좌측 정렬] 정렬 라벨과 콤보박스
        sheet_controls_layout.addWidget(QLabel("정렬"))
        sheet_controls_layout.addWidget(self.sheet_sort_combo)

        # [중요] 중간에 빈 공간(스프링)을 추가하여 Key 그룹을 우측 끝으로 밀어냅니다.
        sheet_controls_layout.addStretch()

        # [우측 정렬] Key 라벨과 콤보박스
        sheet_controls_layout.addWidget(QLabel("Key"))
        sheet_controls_layout.addWidget(self.key_filter_combo)

        # 플레이리스트 검색 및 정렬
        self.playlist_search_timer = QTimer(self)
        self.playlist_search_timer.setSingleShot(True)
        self.playlist_search_timer.setInterval(300)
        self.playlist_search_timer.timeout.connect(self.perform_playlist_search_filter)

        self.playlist_search_input = QLineEdit()
        self.playlist_search_input.setPlaceholderText("🔍 리스트 검색...")
        self.playlist_search_input.textChanged.connect(self.playlist_search_timer.start)

        self.btn_reset_playlist_search = QPushButton()
        self.set_icon_button(
            self.btn_reset_playlist_search, QStyle.SP_DialogResetButton, "초기화"
        )
        self.btn_reset_playlist_search.clicked.connect(
            self.reset_playlist_search_filter
        )

        self.playlist_sort_combo = QComboBox()
        self.playlist_sort_combo.addItems(
            ["날짜 (최신)", "날짜 (오래된)", "이름 ▲", "이름 ▼"]
        )
        self.playlist_sort_combo.setFixedWidth(110)
        self.playlist_sort_combo.setCurrentText("날짜 (최신)")
        self.playlist_sort_combo.currentTextChanged.connect(
            self.change_playlist_sort_order
        )

        playlist_control_layout = QHBoxLayout()
        playlist_control_layout.addWidget(self.playlist_search_input)
        playlist_control_layout.addWidget(self.btn_reset_playlist_search)
        playlist_control_layout.addWidget(self.playlist_sort_combo)

        # 타이틀 라벨
        self.tree_title = QLabel("악보 선택")
        self.tree_title.setObjectName("panelTitle")
        self.list_title = QLabel("찬양 리스트")
        self.list_title.setObjectName("panelTitle")

        # --- 4. 중앙 패널 (미리보기 & Inspector) ---
        self.preview_label = QLabel("파일을 선택하세요")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setFont(QFont("맑은 고딕", 12))

        self.preview_scroll_area = QScrollArea()
        self.preview_scroll_area.setWidgetResizable(True)
        self.preview_scroll_area.setWidget(self.preview_label)
        self.preview_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.preview_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

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

        # 싱글 쇼 버튼
        self.btn_show_single = QPushButton()
        self.set_icon_button(
            self.btn_show_single,
            QStyle.SP_DesktopIcon,
            "이 곡만 바로 쇼하기 (F6)",
            " 이 곡 쇼하기 (F6)",
        )
        self.btn_show_single.setShortcut(Qt.Key_F6)
        self.btn_show_single.clicked.connect(self.start_single_song_show)

        # Inspector (곡 정보 패널)
        inspector_group_box = QWidget()
        inspector_main_layout = QVBoxLayout(inspector_group_box)
        inspector_main_layout.setContentsMargins(10, 10, 10, 10)
        inspector_main_layout.setSpacing(5)

        # 메타데이터 접기/펼치기 헤더
        header_layout = QHBoxLayout()
        self.btn_toggle_metadata = QToolButton()
        self.btn_toggle_metadata.setText("조와 가사 ▼")
        self.btn_toggle_metadata.setCheckable(True)
        self.btn_toggle_metadata.setChecked(True)
        self.btn_toggle_metadata.clicked.connect(self.toggle_metadata_panel)
        header_layout.addWidget(self.btn_toggle_metadata)
        header_layout.addStretch()
        inspector_main_layout.addLayout(header_layout)

        top_row_layout = QHBoxLayout()
        self.inspector_key_combo = QComboBox()
        self.inspector_key_combo.addItems(
            ["", "A", "A#", "B", "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#"]
        )
        self.inspector_key_combo.setFixedWidth(60)

        self.btn_google_lyrics = QPushButton()
        self.set_icon_button(
            self.btn_google_lyrics, "🌐", "Google 가사 검색", "가사검색"
        )
        self.btn_google_lyrics.clicked.connect(self.search_lyrics_on_google)

        top_row_layout.addWidget(QLabel("Key:"))
        top_row_layout.addWidget(self.inspector_key_combo)
        top_row_layout.addStretch()
        top_row_layout.addWidget(self.btn_google_lyrics)

        # 가사 입력창
        self.inspector_lyrics_edit = QTextEdit()
        self.inspector_lyrics_edit.setAcceptRichText(False)
        self.inspector_lyrics_edit.setPlaceholderText("가사 입력")
        self.inspector_lyrics_edit.setMinimumHeight(200)

        # 하단 버튼 그룹
        self.btn_sync_drive = QPushButton()
        self.set_icon_button(
            self.btn_sync_drive,
            QStyle.SP_DriveNetIcon,
            "온라인 악보 받기",
            " 악보동기화",
        )
        self.btn_sync_drive.clicked.connect(self.run_google_sync)
        if not GOOGLE_LIB_AVAILABLE:
            self.btn_sync_drive.setEnabled(False)

        self.btn_launch_capture = QPushButton()
        self.btn_launch_capture.clicked.connect(self.launch_capture_tool)
        self.set_icon_button(
            self.btn_launch_capture, "📸", "웹 또는 파일로 악보 수집", " 악보수집도구"
        )

        self.btn_sync_db = QPushButton()
        self.set_icon_button(self.btn_sync_db, "⬇", "DB 내려받기", "가사DB다운")
        self.btn_sync_db.clicked.connect(self.run_db_sync)

        self.btn_push_db = QPushButton()
        self.set_icon_button(self.btn_push_db, "⬆", "DB 올리기", "가사DB업로드")
        self.btn_push_db.clicked.connect(self.run_db_push)

        if not GOOGLE_LIB_AVAILABLE:
            self.btn_sync_db.setEnabled(False)
            self.btn_push_db.setEnabled(False)

        db_buttons_layout = QHBoxLayout()
        db_buttons_layout.addWidget(self.btn_sync_drive)
        db_buttons_layout.addWidget(self.btn_launch_capture)
        db_buttons_layout.addStretch()
        db_buttons_layout.addWidget(self.btn_sync_db)
        db_buttons_layout.addWidget(self.btn_push_db)

        # 메타데이터 영역(접기/펼치기 대상) 컨테이너
        self.metadata_container = QWidget()
        metadata_layout = QVBoxLayout(self.metadata_container)
        metadata_layout.setContentsMargins(0, 0, 0, 0)
        metadata_layout.setSpacing(5)
        metadata_layout.addLayout(top_row_layout)
        metadata_layout.addWidget(self.inspector_lyrics_edit)

        inspector_main_layout.addWidget(self.metadata_container)
        inspector_main_layout.addLayout(db_buttons_layout)

        # 기본 상태: 조와 가사(메타데이터) 영역을 접은 상태로 시작
        self.metadata_container.hide()
        self.btn_toggle_metadata.setText("조와 가사 ▶")
        self.btn_toggle_metadata.setChecked(False)

        self.inspector_key_combo.currentTextChanged.connect(
            self.on_inspector_key_changed
        )
        self.inspector_lyrics_edit.installEventFilter(self)
        self.load_metadata_to_inspector(None)

        # --- 5. 즐겨찾기 및 선택 버튼 ---
        self.btn_add_favorite = QPushButton()
        self.set_icon_button(self.btn_add_favorite, "⭐+", "즐겨찾기 추가", "추가")
        self.btn_add_favorite.clicked.connect(self.add_current_to_favorites)

        self.btn_remove_favorite = QPushButton()
        self.set_icon_button(self.btn_remove_favorite, "⭐-", "즐겨찾기 삭제", "삭제")
        self.btn_remove_favorite.clicked.connect(self.remove_current_from_favorites)

        self.btn_toggle_favorites_view = QPushButton()
        self.set_icon_button(
            self.btn_toggle_favorites_view, "⭐List", "즐겨찾기 모드 보기", "모아보기"
        )
        self.btn_toggle_favorites_view.setCheckable(True)
        self.btn_toggle_favorites_view.clicked.connect(self.toggle_favorites_view)

        favorites_button_layout = QHBoxLayout()
        favorites_button_layout.addWidget(self.btn_add_favorite)
        favorites_button_layout.addWidget(self.btn_remove_favorite)
        favorites_button_layout.addWidget(self.btn_toggle_favorites_view)

        self.btn_add_selected = QPushButton()
        self.set_icon_button(
            self.btn_add_selected,
            QStyle.SP_ArrowRight,
            "선택 항목을 리스트로 보내기",
            " 리스트에 추가",
        )
        self.btn_add_selected.clicked.connect(self.add_selected_file_single)

        # --- 6. 우측 패널 버튼 및 제어 ---
        self.status_bar_label = QLabel()

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        self.list_widget.setDragEnabled(True)
        self.list_widget.setAcceptDrops(True)
        self.list_widget.setDragDropMode(QListWidget.InternalMove)
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.itemDoubleClicked.connect(self.handle_list_double_click)
        self.list_widget.itemClicked.connect(self.handle_list_click)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(
            self.show_list_widget_context_menu
        )
        self.list_widget.setMouseTracking(True)
        self.list_widget.mouseMoveEvent = self.list_widget_mouse_move_event

        # 리스트 제어 버튼들
        self.btn_delete = QPushButton()
        self.set_icon_button(self.btn_delete, QStyle.SP_TrashIcon, "선택 삭제", "삭제")
        self.btn_delete.clicked.connect(self.delete_selected_items)

        self.btn_delete_all = QPushButton()
        self.set_icon_button(self.btn_delete_all, "🗑️", "전체 삭제", "전체삭제")
        self.btn_delete_all.clicked.connect(self.delete_all_items)

        self.btn_insert_intermission = QPushButton()
        self.set_icon_button(
            self.btn_insert_intermission, "☕", "인터미션 추가", "인터미션"
        )
        self.btn_insert_intermission.clicked.connect(self.insert_intermission_item)

        # [추가] 텍스트 추가 버튼
        self.btn_add_text = QPushButton()
        self.set_icon_button(
            self.btn_add_text, "T", "텍스트(성경/문구) 추가", "텍스트 추가"
        )
        self.btn_add_text.clicked.connect(self.add_text_item)

        # 이동 버튼
        self.btn_move_up = QPushButton()
        self.set_icon_button(self.btn_move_up, QStyle.SP_ArrowUp, "위로", "위")
        self.btn_move_down = QPushButton()
        self.set_icon_button(self.btn_move_down, QStyle.SP_ArrowDown, "아래로", "아래")
        self.btn_move_top = QPushButton()
        self.set_icon_button(self.btn_move_top, "▲", "맨 위로", "맨위")
        self.btn_move_bottom = QPushButton()
        self.set_icon_button(self.btn_move_bottom, "▼", "맨 아래로", "맨아래")

        self.btn_move_up.clicked.connect(self.move_item_up)
        self.btn_move_down.clicked.connect(self.move_item_down)
        self.btn_move_top.clicked.connect(self.move_item_top)
        self.btn_move_bottom.clicked.connect(self.move_item_bottom)

        self.btn_save_list = QPushButton()
        self.set_icon_button(
            self.btn_save_list, QStyle.SP_DialogSaveButton, "리스트 저장", "저장"
        )
        self.btn_save_list.clicked.connect(self.save_list)

        self.btn_load_list = QPushButton()
        self.set_icon_button(
            self.btn_load_list, QStyle.SP_DialogOpenButton, "리스트 불러오기", "열기"
        )
        self.btn_load_list.clicked.connect(self.load_list)

        # [레이아웃 수정] 버튼들을 보기 좋게 배치
        list_control_layout_1 = QHBoxLayout()
        list_control_layout_1.addWidget(self.btn_insert_intermission)
        list_control_layout_1.addWidget(self.btn_add_text)
        list_control_layout_1.addWidget(self.btn_delete)
        list_control_layout_1.addWidget(self.btn_delete_all)

        list_control_layout_2 = QHBoxLayout()
        list_control_layout_2.addWidget(self.btn_move_top)
        list_control_layout_2.addWidget(self.btn_move_up)
        list_control_layout_2.addWidget(self.btn_move_down)
        list_control_layout_2.addWidget(self.btn_move_bottom)
        
        list_control_layout_3 = QHBoxLayout()
        list_control_layout_3.addWidget(self.btn_save_list)
        list_control_layout_3.addWidget(self.btn_load_list)

        # [Clean up] Unused layout block removed to avoid reparenting issues

        # 시작 버튼
        self.btn_start_from_first = QPushButton()
        self.set_icon_button(
            self.btn_start_from_first,
            QStyle.SP_MediaPlay,
            "처음부터 시작 (F5)",
            " 처음부터 (F5)",
        )
        self.btn_start_from_first.setShortcut(Qt.Key_F5)
        self.btn_start_from_first.clicked.connect(self.start_show)

        self.btn_start_from_current = QPushButton()
        self.set_icon_button(
            self.btn_start_from_current,
            QStyle.SP_MediaSkipForward,
            "현재 곡부터 시작 (Shift+F5)",
            " 현재부터 (Shift+F5)",
        )
        self.btn_start_from_current.setShortcut(QKeySequence("Shift+F5"))
        self.btn_start_from_current.clicked.connect(self.start_show_from_current)

        # 쇼 제어 (듀얼 모니터 등)
        self.btn_toggle_dual_viewer = QPushButton()
        self.set_icon_button(
            self.btn_toggle_dual_viewer,
            QStyle.SP_ComputerIcon,
            "쇼창 켜기/끄기",
            " 쇼창 켜기",
        )
        self.btn_toggle_dual_viewer.setCheckable(True)
        self.btn_toggle_dual_viewer.clicked.connect(self.toggle_dual_monitor_viewer)

        self.btn_black_screen = QPushButton()
        self.set_icon_button(
            self.btn_black_screen, "Black", "블랙 스크린 (B)", "블랙(B)"
        )
        self.btn_black_screen.setShortcut(Qt.Key_B)
        self.btn_black_screen.clicked.connect(self.remote_toggle_black)

        self.btn_logo_screen = QPushButton()
        self.set_icon_button(self.btn_logo_screen, "Logo", "로고 화면 (L)", "로고(L)")
        self.btn_logo_screen.setShortcut(Qt.Key_L)
        self.btn_logo_screen.clicked.connect(self.remote_toggle_logo)

        screen_control_layout = QHBoxLayout()
        screen_control_layout.addWidget(self.btn_black_screen)
        screen_control_layout.addWidget(self.btn_logo_screen)

        self.monitor_combo = QComboBox()
        self.init_monitor_selection()

        # ▼▼▼ [여기부터 추가하세요] ▼▼▼
        # 실행 중 모니터 연결/해제 감지하여 목록 갱신
        app_instance = QApplication.instance()
        if app_instance:
            app_instance.screenAdded.connect(
                lambda screen: self.init_monitor_selection()
            )
            app_instance.screenRemoved.connect(
                lambda screen: self.init_monitor_selection()
            )
        # ▲▲▲ [여기까지 추가] ▲▲▲

        dual_control_layout = QVBoxLayout()
        dual_control_layout.setSpacing(8)

        start_buttons_layout = QHBoxLayout()
        start_buttons_layout.addWidget(self.btn_start_from_first)
        start_buttons_layout.addWidget(self.btn_start_from_current)

        dual_control_layout.addLayout(start_buttons_layout)
        dual_control_layout.addWidget(self.btn_toggle_dual_viewer)
        dual_control_layout.addWidget(self.monitor_combo)
        dual_control_layout.addLayout(screen_control_layout)

        dual_group = QGroupBox()  # 타이틀 텍스트 제거
        dual_group.setLayout(dual_control_layout)

        # 내부 여백을 줄여서 더 컴팩트하게 만듦
        dual_control_layout.setContentsMargins(5, 5, 5, 5)

        # 스타일시트 수정: margin-top 제거, title 스타일 제거
        dual_group.setStyleSheet(
            """
            QGroupBox {
                border: 2px solid #555555;
                border-radius: 8px;
                margin-top: 5px;  /* 상단 여백 최소화 */
                padding: 0px;
            }
            /* 타이틀 관련 스타일 제거됨 */
        """
        )

        # --- [설정 버튼 및 다이얼로그 구성] ---
        # 1. 설정 다이얼로그 생성 (기본 QDialog 사용)
        self.settings_dialog = QDialog(self)

        # 2. 기본 설정 (타이틀, 크기)
        self.settings_dialog.setWindowTitle("환경설정")
        self.settings_dialog.resize(500, 450)

        # 3. 스타일 설정 (카드 스타일 제거 -> 흰색 배경 적용)
        # 둥근 모서리나 그림자 없이 깔끔한 기본 창으로 만듭니다.
        # self.settings_dialog.setStyleSheet("background-color: #FFFFFF;")

        # 4. 레이아웃 설정
        settings_layout = QVBoxLayout(self.settings_dialog)
        settings_layout.setSpacing(20)
        settings_layout.setContentsMargins(20, 20, 20, 20)

        # 경로 설정 그룹
        paths_group = QGroupBox("폴더 경로 설정")
        paths_layout = QVBoxLayout(paths_group)

        sheet_path_layout = QHBoxLayout()
        sheet_path_layout.addWidget(QLabel("📂 악보 폴더:"))
        sheet_path_layout.addWidget(self.path_label)
        sheet_path_layout.addWidget(self.btn_change_folder)
        paths_layout.addLayout(sheet_path_layout)

        playlist_path_layout = QHBoxLayout()
        playlist_path_layout.addWidget(QLabel("📂 리스트 폴더:"))
        playlist_path_layout.addWidget(self.playlist_path_label)
        playlist_path_layout.addWidget(self.btn_change_playlist_folder)
        paths_layout.addLayout(playlist_path_layout)

        settings_layout.addWidget(paths_group)

        # 디스플레이 설정 위젯들 정의
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(self.themes.keys())
        self.theme_combo.setCurrentText(self.current_theme)
        self.theme_combo.currentTextChanged.connect(self.set_theme)

        self.zoom_label = QLabel()
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(50, 100)
        self.zoom_slider.setValue(self.initial_zoom_percentage)
        self.zoom_slider.valueChanged.connect(self.update_zoom_label)
        self.update_zoom_label(self.initial_zoom_percentage)

        self.scroll_label = QLabel()
        self.scroll_slider = QSlider(Qt.Horizontal)
        self.scroll_slider.setRange(10, 150)
        self.scroll_slider.setValue(self.scroll_sensitivity)
        self.scroll_slider.valueChanged.connect(self.update_scroll_label)
        self.update_scroll_label(self.scroll_sensitivity)

        self.logo_path_label = QLineEdit(self.logo_image_path)
        self.logo_path_label.setReadOnly(True)
        self.logo_path_label.setPlaceholderText("로고 없음")
        self.btn_change_logo = QPushButton("변경")
        self.btn_change_logo.clicked.connect(self.change_logo_image)

        # 디스플레이 설정 그룹
        display_group = QGroupBox("디스플레이 및 동작 설정")
        display_layout = QVBoxLayout(display_group)
        display_layout.setSpacing(15)

        theme_layout = QHBoxLayout()
        theme_layout.addWidget(QLabel("🎨 테마 선택:"))
        theme_layout.addWidget(self.theme_combo)
        display_layout.addLayout(theme_layout)

        zoom_layout = QHBoxLayout()
        zoom_layout.addWidget(QLabel("🔍 기본 줌:"))
        zoom_layout.addWidget(self.zoom_slider)
        zoom_layout.addWidget(self.zoom_label)
        display_layout.addLayout(zoom_layout)

        scroll_layout_box = QHBoxLayout()
        scroll_layout_box.addWidget(QLabel("🖱️ 스크롤 감도:"))
        scroll_layout_box.addWidget(self.scroll_slider)
        scroll_layout_box.addWidget(self.scroll_label)
        display_layout.addLayout(scroll_layout_box)

        logo_layout = QHBoxLayout()
        logo_layout.addWidget(QLabel("🖼️ 로고 이미지:"))
        logo_layout.addWidget(self.logo_path_label)
        logo_layout.addWidget(self.btn_change_logo)
        display_layout.addLayout(logo_layout)

        settings_layout.addWidget(display_group)

        # 닫기 버튼
        btn_close_settings = QPushButton("닫기")
        btn_close_settings.setFixedHeight(40)
        btn_close_settings.clicked.connect(self.settings_dialog.accept)
        settings_layout.addWidget(btn_close_settings)

        # 메인 화면용 설정 버튼
        self.btn_open_settings = QPushButton()
        self.set_icon_button(
            self.btn_open_settings, "⚙️", "환경설정 (폴더, 테마 등)", " 환경설정"
        )
        self.btn_open_settings.clicked.connect(self.settings_dialog.show)

        # 우측 패널 레이아웃 재구성
        list_control_grid = QHBoxLayout()
        list_control_grid.addWidget(self.btn_move_top)
        list_control_grid.addWidget(self.btn_move_up)
        list_control_grid.addWidget(self.btn_move_down)
        list_control_grid.addWidget(self.btn_move_bottom)

        list_edit_layout = QHBoxLayout()
        list_edit_layout.addWidget(self.btn_delete)
        list_edit_layout.addWidget(self.btn_delete_all)
        list_edit_layout.addWidget(self.btn_insert_intermission)
        list_edit_layout.addWidget(self.btn_save_list)
        list_edit_layout.addWidget(self.btn_load_list)

        # [수정] 단축키 영역: 타이틀 제거 및 내부 여백 최소화 (리스트 영역 확장 효과)
        shortcut_group_box = QGroupBox()
        # 스타일시트로 상단 마진 제거하여 공간 확보
        shortcut_group_box.setStyleSheet(
            """
            QGroupBox {
                border: 1px solid #CCCCCC;
                border-radius: 6px;
                margin-top: 5px;
                padding-top: 0px;
            }
        """
        )

        shortcut_layout = QVBoxLayout(shortcut_group_box)
        # 레이아웃 내부 여백을 촘촘하게 설정
        shortcut_layout.setContentsMargins(10, 8, 10, 8)
        shortcut_layout.setSpacing(2)

        shortcut_label = QLabel(
            "PgDn/→: 다음 | PgUp/←: 이전\n"
            "B: 블랙 | L: 로고 | Esc: 종료\n"
            "+/-: 확대/축소"
        )
        shortcut_label.setAlignment(Qt.AlignLeft)
        shortcut_layout.addWidget(shortcut_label)

        # 버튼 ObjectName 설정 (스타일)
        self.btn_show_single.setObjectName("primary")
        self.btn_start_from_first.setObjectName("primary")
        self.btn_start_from_current.setObjectName("primary")
        self.btn_add_selected.setObjectName("primary")

        # --- [UI 조립] ---

        # 1. 좌측 상단 패널 (파일 탐색)
        top_container = QWidget()
        self.decorate_as_card(top_container)
        top_layout = QVBoxLayout(top_container)
        top_layout.setContentsMargins(15, 15, 15, 15)
        top_layout.setSpacing(8)

        top_layout.addWidget(self.tree_title)
        top_layout.addLayout(search_layout)
        top_layout.addLayout(sheet_controls_layout)
        top_layout.addWidget(self.tree)
        top_layout.addWidget(self.status_bar_label)
        top_layout.addLayout(favorites_button_layout)
        top_layout.addWidget(self.btn_add_selected)

        # 2. 좌측 하단 패널 (플레이리스트 탐색)
        bottom_container = QWidget()
        self.decorate_as_card(bottom_container)
        bottom_layout = QVBoxLayout(bottom_container)
        bottom_layout.setContentsMargins(15, 15, 15, 15)
        bottom_layout.setSpacing(8)

        bottom_layout.addWidget(self.list_title)
        bottom_layout.addLayout(playlist_control_layout)
        bottom_layout.addWidget(self.playlist_tree)
        self.btn_playlist_stats = QPushButton("📊 플레이 리스트 곡 통계")
        self.btn_playlist_stats.clicked.connect(self.open_playlist_song_stats_dialog)
        bottom_layout.addWidget(self.btn_playlist_stats)

        # 좌측 스플리터
        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.addWidget(top_container)
        left_splitter.addWidget(bottom_container)
        left_splitter.setSizes([500, 300])
        left_splitter.setHandleWidth(10)

        # 3. 중앙 패널 (미리보기)
        preview_widget = QWidget()
        self.decorate_as_card(preview_widget)
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(15, 15, 15, 15)
        preview_layout.setSpacing(8)

        self.preview_title = QLabel("미리보기")
        self.preview_title.setObjectName("panelTitle")

        preview_layout.addWidget(self.preview_title)
        preview_layout.addWidget(self.preview_container)
        preview_layout.addWidget(self.btn_show_single)

        self.decorate_as_card(inspector_group_box)

        # 중앙 스플리터
        self.center_splitter = QSplitter(Qt.Vertical)
        self.center_splitter.addWidget(preview_widget)
        self.center_splitter.addWidget(inspector_group_box)
        # 기본값: 메타데이터 패널이 접힌 상태를 기준으로 넓게 설정
        self.center_splitter.setSizes([850, 80])
        self.center_splitter.setHandleWidth(10)

        # 4. 우측 패널 (리스트 및 제어)
        right_container = QWidget()
        self.decorate_as_card(right_container)
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(15, 15, 15, 15)
        right_layout.setSpacing(10)

        right_title = QLabel("큐시트(순서)")
        right_title.setObjectName("panelTitle")

        right_layout.addWidget(right_title)
        right_layout.addWidget(self.list_widget, 1)
        
        # [수정] 새로 만든 레이아웃 적용
        right_layout.addLayout(list_control_layout_1)
        right_layout.addLayout(list_control_layout_2)
        right_layout.addLayout(list_control_layout_3)
        
        # right_layout.addLayout(list_control_grid) # 기존 코드 제거
        # right_layout.addLayout(list_edit_layout)  # 기존 코드 제거
        right_layout.addWidget(dual_group)
        right_layout.addWidget(self.btn_open_settings)
        right_layout.addWidget(shortcut_group_box)

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        # 2 : 3 : 2 비율
        main_layout.addWidget(left_splitter, 2)
        main_layout.addWidget(self.center_splitter, 3)
        main_layout.addWidget(right_container, 2)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)
        self.menuBar().setVisible(False)

        # --- 초기화 마무리 ---
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
        self.warm_up_list_widget()

    def decorate_as_card(self, widget):
        """위젯을 카드 형태로 꾸며줍니다 (ObjectName 설정 및 그림자 효과)."""
        widget.setObjectName("card")

        # 그림자 효과 추가
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setXOffset(0)
        shadow.setYOffset(4)
        shadow.setColor(QColor(0, 0, 0, 30))  # 아주 연한 그림자
        widget.setGraphicsEffect(shadow)

    def delete_tree_file(self, file_path):
        """트리 뷰에서 선택된 파일을 삭제하고 관련 데이터를 정리합니다."""
        file_name = os.path.basename(file_path)
        reply = QMessageBox.question(
            self,
            "파일 삭제 확인",
            f"'{file_name}' 파일을 정말로 삭제하시겠습니까?\n"
            f"이 작업은 되돌릴 수 없으며, 로컬 디스크에서 완전히 삭제됩니다.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            try:
                # 1. 파일 삭제
                os.remove(file_path)

                # 2. 즐겨찾기 목록에서 제거
                if file_path in self.favorites:
                    self.favorites.remove(file_path)
                    self.save_favorites()

                # 3. 메타데이터 캐시 및 DB 제거
                if file_path in self.metadata_cache:
                    del self.metadata_cache[file_path]

                try:
                    con = sqlite3.connect(self.db_path)
                    cur = con.cursor()
                    cur.execute(
                        "DELETE FROM song_metadata WHERE file_path = ?",
                        (file_path,),
                    )
                    con.commit()
                    con.close()
                except Exception as e:
                    print(f"DB 데이터 삭제 실패: {e}")

                # 4. 화면 갱신
                self.proxy_model.invalidate()
                self.current_preview_path = None
                self.update_preview_panel(None)
                self.load_metadata_to_inspector(None)

                self.status_bar_label.setText(f"삭제됨: {file_name}")

            except OSError as e:
                QMessageBox.critical(
                    self,
                    "파일 삭제 오류",
                    f"파일을 삭제하는 중 오류가 발생했습니다: {e}",
                )

    # --- [추가] 인터미션 삽입 메서드 ---
    def add_text_item(self):
        """텍스트 슬라이드를 추가합니다."""
        # 기본값(마지막 사용 값)으로 초기화된 데이터 전달
        initial_data = {
            "font_family": getattr(self, "text_slide_font_family", "맑은 고딕"),
            "font_size": getattr(self, "text_slide_font_size", 50),
            "theme": "말씀 (Warm Paper)", # 기본 테마
            "text": ""
        }
        
        dialog = TextSlideDialog(self, initial_data)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            text = data["text"]
            theme = data["theme"]
            
            if not text:
                return

            # 변경된 설정 저장 (다음 번에 기본값으로 사용)
            self.text_slide_font_family = data["font_family"]
            self.text_slide_font_size = data["font_size"]
            self.save_settings()

            # 리스트 아이템 생성
            item = QListWidgetItem()
            
            # 아이템 텍스트 (목록에 보여질 이름)
            summary = text.split('\n')[0]
            if len(summary) > 20:
                summary = summary[:20] + "..."
            item.setText(f"📖 {summary} ({theme})")
            
            # 데이터 저장
            item.setData(Qt.UserRole, text)          # 텍스트 내용
            item.setData(Qt.UserRole + 1, False)     # 인터미션 아님
            item.setData(Qt.UserRole + 2, "text")    # 타입: 텍스트
            item.setData(Qt.UserRole + 3, {
                "theme": theme, 
                "font_size": data["font_size"],
                "font_family": data["font_family"]
            })
            
            self.list_widget.addItem(item)
            self.list_widget.setCurrentItem(item)

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
                    lyrics TEXT,
                    updated_at TEXT,
                    updated_by TEXT,
                    dirty INTEGER DEFAULT 0
                )
            """
            )
            # 기존 DB에서 컬럼이 부족한 경우를 대비해 보강
            cur.execute("PRAGMA table_info(song_metadata)")
            cols = {row[1] for row in cur.fetchall()}
            if "updated_at" not in cols:
                cur.execute("ALTER TABLE song_metadata ADD COLUMN updated_at TEXT")
            if "updated_by" not in cols:
                cur.execute("ALTER TABLE song_metadata ADD COLUMN updated_by TEXT")
            if "dirty" not in cols:
                cur.execute(
                    "ALTER TABLE song_metadata ADD COLUMN dirty INTEGER DEFAULT 0"
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
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            editor = getattr(self, "editor_name", "") or ""
            cur.execute(
                """
                INSERT INTO song_metadata (file_path, song_key, lyrics, updated_at, updated_by, dirty)
                VALUES (?, ?, ?, ?, ?, 1)
                ON CONFLICT(file_path) DO UPDATE SET
                    song_key=excluded.song_key,
                    lyrics=excluded.lyrics,
                    updated_at=excluded.updated_at,
                    updated_by=excluded.updated_by,
                    dirty=1
            """,
                (file_path, song_key, lyrics, now, editor),
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

    def list_widget_mouse_move_event(self, event):
        """큐시트 리스트에서 마우스 이동 시 툴팁으로 악보 미리보기를 표시합니다."""
        item = self.list_widget.itemAt(event.position().toPoint())
        if item is not None and item != self.current_list_tooltip_item:
            self.current_list_tooltip_item = item
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
                        self.list_widget,
                    )
                else:
                    QToolTip.hideText()
            else:
                QToolTip.hideText()
        elif item is None:
            QToolTip.hideText()
            self.current_list_tooltip_item = None
        QListWidget.mouseMoveEvent(self.list_widget, event)

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
        # 플레이리스트 미리보기에서 선택된 항목이 있는지 확인
        if self.preview_stack.currentWidget() == self.preview_list_widget:
            selected_items = self.preview_list_widget.selectedItems()
            if selected_items:
                item = selected_items[0]
                path = item.data(Qt.UserRole)
                if path and os.path.isfile(path):
                    is_image = path.lower().endswith(tuple(self.image_extensions))
                    if is_image:
                        single_data = [{"path": path, "is_intermission": False}]
                        self.open_viewer_window(single_data, 0)
                        return
                    else:
                        QMessageBox.warning(
                            self,
                            "알림",
                            "이미지 파일만 쇼를 시작할 수 있습니다. (.pls 파일 등은 불가)",
                        )
                        return
        
        # 기존 로직: current_preview_path 사용
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
            "다크": {
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

    # [추가] 텍스트 슬라이드 수정 메서드 (클래스 내부에 추가)
    def edit_text_slide(self, item):
        """기존 텍스트 슬라이드를 수정합니다."""
        text = item.data(Qt.UserRole)
        extra = item.data(Qt.UserRole + 3) or {}
        theme = extra.get("theme", "기본")
        font_size = extra.get("font_size", 50)
        font_family = extra.get("font_family", "맑은 고딕")
        
        initial_data = {
            "text": text,
            "theme": theme,
            "font_size": font_size,
            "font_family": font_family
        }
        
        dialog = TextSlideDialog(self, initial_data)
        if dialog.exec() == QDialog.Accepted:
            new_data = dialog.get_data()
            new_text = new_data["text"]
            new_theme = new_data["theme"]
            new_font_size = new_data["font_size"]
            new_font_family = new_data["font_family"]
            
            # 아이템 업데이트
            summary = new_text.split('\n')[0]
            if len(summary) > 20:
                summary = summary[:20] + "..."
            item.setText(f"📖 {summary} ({new_theme})")
            
            item.setData(Qt.UserRole, new_text)
            item.setData(Qt.UserRole + 3, {
                "theme": new_theme, 
                "font_size": new_font_size,
                "font_family": new_font_family
            })

    def apply_theme(self, theme_name):
        """Modern Flat Style 테마 적용 (라벨 투명화 및 다크모드 완벽 지원)"""

        theme = self.themes.get(theme_name, self.themes["기본 (밝게)"])

        is_dark = "다크" in theme_name or "어둡게" in theme_name

        if is_dark:
            main_bg = theme.get("base", "#121212")
            card_bg = theme.get("window", "#1E1E1E")
            text_col = theme.get("text", "#E0E0E0")
            border_col = theme.get("border", "#333333")
        else:
            main_bg = "#F5F5F7"
            card_bg = theme.get("window", "#FFFFFF")
            text_col = theme.get("text", "#333333")
            border_col = theme.get("border", "#E5E5E5")

        highlight = theme.get("highlight", "#3CB371")
        highlight_text = theme.get("highlight_text", "#FFFFFF")
        button_bg = theme.get("button", "#F5F5F5")
        button_text = theme.get("button_text", "#000000")

        stylesheet = f"""
            /* ===== Main Window & Dialogs ===== */
            QMainWindow {{
                background-color: {main_bg};
            }}
            QDialog {{
                background-color: {card_bg};
                color: {text_col};
            }}

            /* ===== Global ===== */
            QWidget {{
                background-color: {main_bg};
                color: {text_col};
                font-family: '맑은 고딕', 'Malgun Gothic', sans-serif;
                font-size: 11pt;
            }}

            /* [중요] 라벨 전용 스타일: 배경을 투명하게 해서 부모(카드/메인) 색상에 자연스럽게 녹아들게 함 */
            QLabel {{
                background-color: transparent;
                color: {text_col};
                border: none;
            }}
            
            /* ===== Cards (Containers) ===== */
            QWidget#card {{
                background-color: {card_bg};
                border: 1px solid {border_col};
                border-radius: 10px;
            }}
            
            /* ===== Typography ===== */
            /* 패널 타이틀은 폰트 크기만 더 키움 (배경 투명은 위 QLabel 규칙을 따름) */
            QLabel#panelTitle {{
                font-size: 14pt;
                font-weight: bold;
                padding-bottom: 5px;
            }}
            
            /* ===== Inputs & Lists ===== */
            QLineEdit, QComboBox, QPlainTextEdit, QTextEdit {{
                background-color: {card_bg};
                border: 1px solid {border_col};
                border-radius: 6px;
                padding: 6px;
                color: {text_col};
            }}
            
            QTreeView, QListWidget, QScrollArea {{
                background-color: {card_bg};
                border: 1px solid {border_col};
                border-radius: 6px;
                outline: none;
            }}
            
            QTreeView::item, QListWidget::item {{
                padding: 6px;
                border-bottom: 1px solid transparent;
            }}
            
            QTreeView::item:hover, QListWidget::item:hover {{
                background-color: {main_bg};
                border-radius: 4px;
                color: {text_col};
            }}
            
            QTreeView::item:selected, QListWidget::item:selected {{
                background-color: {highlight};
                color: {highlight_text};
                border-radius: 4px;
            }}

            /* ===== Splitter ===== */
            QSplitter::handle {{
                background-color: transparent;
                margin: 0px 5px;
            }}

            /* ===== Buttons ===== */
            QPushButton {{
                background-color: {button_bg};
                color: {button_text};
                border: 1px solid {border_col};
                border-radius: 6px;
                padding: 8px 15px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {button_bg}; 
                border: 1px solid {highlight};
                color: {button_text};
            }}
            QPushButton:pressed {{
                background-color: {button_bg};
                border: 2px solid {highlight};
            }}
            
            /* Primary Button (강조 버튼) */
            QPushButton#primary {{
                background-color: {highlight};
                color: {highlight_text};
                border: none;
            }}
            QPushButton#primary:hover {{
                border: 2px solid {card_bg};
            }}
            
            /* ScrollBars */
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: #D1D5DB;
                border-radius: 4px;
                min-height: 30px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}

            QGroupBox {{
                background-color: {card_bg};
                border: 1px solid {border_col};
                border-radius: 10px;
                margin-top: 20px;
                padding-top: 15px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
                font-weight: bold;
                color: {text_col};
            }}
        """
        self.setStyleSheet(stylesheet)

        # 미리보기 라벨은 이미 위 QLabel 규칙으로 투명이 되었으나, 안전장치로 유지
        self.preview_label.setStyleSheet("background-color: transparent; border: none;")

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
        # Drive 폴더 내 메타데이터 CSV 파일명(공동작업용)
        self.metadata_csv_name = "song_metadata.csv"
        # 중앙 원본 스프레드시트 파일명(공동작업용)
        self.metadata_sheet_name = "song_metadata.csv"
        # 로컬 편집자 이름(업로드 시 기록)
        self.editor_name = os.environ.get("USERNAME") or os.environ.get("USER") or ""

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

                    self.drive_folder_id = settings.get(
                        "drive_folder_id", self.drive_folder_id
                    )
                    self.metadata_csv_name = settings.get(
                        "metadata_csv_name", self.metadata_csv_name
                    )
                    self.metadata_sheet_name = settings.get(
                        "metadata_sheet_name", self.metadata_sheet_name
                    )
                    self.editor_name = settings.get("editor_name", self.editor_name)
                    
                    self.text_slide_font_family = settings.get("text_slide_font_family", "맑은 고딕")
                    self.text_slide_font_size = settings.get("text_slide_font_size", 50)
            else:
                self.text_slide_font_family = "맑은 고딕"
                self.text_slide_font_size = 50
                self.save_settings()
        except (json.JSONDecodeError, TypeError, OSError) as e:
            print(f"설정 로드 오류 (기본값 사용): {e}")
            self.text_slide_font_family = "맑은 고딕"
            self.text_slide_font_size = 50
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
            "metadata_csv_name": self.metadata_csv_name,
            "metadata_sheet_name": self.metadata_sheet_name,
            "metadata_sheet_name": self.metadata_sheet_name,
            "editor_name": self.editor_name,
            "text_slide_font_family": getattr(self, "text_slide_font_family", "맑은 고딕"),
            "text_slide_font_size": getattr(self, "text_slide_font_size", 50),
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

    def toggle_metadata_panel(self):
        """곡 메타데이터 영역을 접거나 펼칩니다. 하단 동기화/DB 버튼은 항상 보이도록 유지합니다."""
        if not hasattr(self, "metadata_container"):
            return
        is_visible = self.metadata_container.isVisible()
        if is_visible:
            self.metadata_container.hide()
            if hasattr(self, "btn_toggle_metadata"):
                self.btn_toggle_metadata.setText("조와 가사 ▶")
                self.btn_toggle_metadata.setChecked(False)
            # 메타데이터를 접으면 미리보기 영역을 더 넓게
            if hasattr(self, "center_splitter"):
                self.center_splitter.setSizes([850, 80])
        else:
            self.metadata_container.show()
            if hasattr(self, "btn_toggle_metadata"):
                self.btn_toggle_metadata.setText("조와 가사 ▼")
                self.btn_toggle_metadata.setChecked(True)
            if hasattr(self, "center_splitter"):
                self.center_splitter.setSizes([700, 160])

    def open_playlist_song_stats_dialog(self):
        """플레이 리스트 곡 통계 다이얼로그를 연다. 인터미션 제외, 메타데이터 미반영."""
        dlg = PlaylistSongStatsDialog(
            self.playlist_path,
            self.sheet_music_path,
            parent=self,
        )
        dlg.exec()

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
        """악보 리스트 정렬 변경 (콤보박스 항목명과 일치시킴)"""
        if text == "이름 ▲":
            self.proxy_model.setSortRole(Qt.DisplayRole)
            self.proxy_model.sort(0, Qt.AscendingOrder)
        elif text == "이름 ▼":
            self.proxy_model.setSortRole(Qt.DisplayRole)
            self.proxy_model.sort(0, Qt.DescendingOrder)
        elif text == "Key ▲":
            self.proxy_model.setSortRole(Qt.UserRole)
            self.proxy_model.sort(0, Qt.AscendingOrder)
        elif text == "Key ▼":
            self.proxy_model.setSortRole(Qt.UserRole)
            self.proxy_model.sort(0, Qt.DescendingOrder)

    def on_key_filter_changed(self, key_text):
        self.proxy_model.set_key_filter(key_text)
        self.update_file_count(self.sheet_music_path)

    def change_playlist_sort_order(self, text):
        """플레이리스트 정렬 변경 (콤보박스 항목명과 일치시킴)"""
        if text == "이름 ▲":
            self.playlist_proxy_model.sort(0, Qt.AscendingOrder)
        elif text == "이름 ▼":
            self.playlist_proxy_model.sort(0, Qt.DescendingOrder)
        elif text == "날짜 (최신)":
            # QFileSystemModel의 3번째 컬럼은 '수정 날짜'입니다.
            self.playlist_proxy_model.sort(3, Qt.DescendingOrder)
        elif text == "날짜 (오래된)":
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

            # [추가됨] 삭제 액션
            action_delete = QAction("삭제", self)
            action_delete.triggered.connect(lambda: self.delete_tree_file(path))
            menu.addAction(action_delete)

        if menu.actions():
            menu.exec(self.tree.viewport().mapToGlobal(pos))

    def show_playlist_context_menu(self, pos):
        index = self.playlist_tree.indexAt(pos)
        menu = QMenu()
        if index.isValid():
            self.playlist_tree.setCurrentIndex(index)
            source_index = self.playlist_proxy_model.mapToSource(index)
            path = self.playlist_model.filePath(source_index)
            if os.path.isfile(path):
                action_add_to_list = QAction("목록에 추가하기", self)
                action_add_to_list.triggered.connect(
                    lambda: self._add_paths_from_pls(path)
                )
                menu.addAction(action_add_to_list)
                menu.addSeparator()
                action_rename = QAction("이름 바꾸기", self)
                action_rename.triggered.connect(
                    lambda: self.playlist_tree.edit(index)
                )
                menu.addAction(action_rename)
                action_delete = QAction("삭제", self)
                action_delete.triggered.connect(
                    lambda: self.delete_playlist_file(path)
                )
                menu.addAction(action_delete)
        menu.addSeparator()
        action_stats = QAction("플레이 리스트 곡 통계 보기", self)
        action_stats.triggered.connect(self.open_playlist_song_stats_dialog)
        menu.addAction(action_stats)
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

            # [추가] 텍스트 아이템 수정 메뉴
            item_type = sel_item.data(Qt.UserRole + 2)
            if item_type == "text":
                menu.addSeparator()
                action_edit_text = QAction("텍스트 수정", self)
                action_edit_text.triggered.connect(lambda: self.edit_text_slide(sel_item))
                menu.addAction(action_edit_text)
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
                
                # 텍스트 아이템(슬라이드)은 저장하지 않음 (요청사항)
                if item.data(Qt.UserRole + 2) == "text":
                    continue
                    
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
                    # 가로 너비를 꽉 채우고, 세로는 비율 유지 (가로 스크롤 없음, 세로 스크롤만 가능)
                    scaled_pixmap = pixmap.scaledToWidth(
                        preview_width, Qt.SmoothTransformation
                    )
                    self.preview_label.setPixmap(scaled_pixmap)
                    self.preview_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
                    self.preview_label.setMinimumWidth(preview_width)
                    self.preview_label.setMaximumWidth(preview_width)
                    self.preview_scroll_area.verticalScrollBar().setValue(0)
                else:
                    self.preview_label.setText("미리보기 영역이 너무 작습니다.")
                    self.preview_label.setAlignment(Qt.AlignCenter)
                    self.preview_label.setMinimumWidth(0)
                    self.preview_label.setMaximumWidth(16777215)
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

    def run_db_sync(self):
        """Drive에 있는 metadata CSV를 내려받아 로컬 song_metadata.db를 갱신합니다."""
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

        if not getattr(self, "metadata_csv_name", ""):
            QMessageBox.warning(
                self,
                "설정 확인",
                "metadata_csv_name 설정이 비어있습니다. (기본: song_metadata.csv)",
            )
            return

        # 2. UI 준비 (다이얼로그 표시)
        self.sync_dialog = SyncProgressDialog(self)
        self.sync_dialog.setWindowTitle("DB 동기화")
        self.sync_dialog.status_label.setText("메타데이터 동기화 준비 중...")
        self.sync_dialog.show()

        # 3. 워커 준비
        syncer_helper = GoogleDriveSync(
            key_file, self.sheet_music_path, self.drive_folder_id, self.app_dir
        )
        self.sync_thread = MetadataSyncThread(
            syncer_helper, self.metadata_csv_name, self.db_path, self.sheet_music_path
        )

        # 4. 시그널 연결
        self.sync_thread.log_signal.connect(self.sync_dialog.append_log)
        self.sync_thread.finished_signal.connect(self.on_db_sync_finished)

        # 5. 시작
        self.sync_thread.start()

    def run_db_push(self):
        """로컬 DB에서 수정한(dirty=1) 메타데이터를 중앙 스프레드시트로 업로드합니다."""
        key_file = os.path.join(self.app_dir, "service_account.json")
        if not os.path.exists(key_file):
            QMessageBox.critical(
                self,
                "설정 오류",
                f"서비스 계정 키 파일(service_account.json)이 없습니다.\n경로: {self.app_dir}",
            )
            return

        if not self.drive_folder_id or "여기에" in self.drive_folder_id:
            QMessageBox.warning(
                self, "설정 확인", "drive_folder_id 설정을 확인해주세요."
            )
            return

        if not getattr(self, "metadata_sheet_name", ""):
            QMessageBox.warning(
                self,
                "설정 확인",
                "metadata_sheet_name 설정이 비어있습니다. (기본: song_metadata)",
            )
            return

        self.sync_dialog = SyncProgressDialog(self)
        self.sync_dialog.setWindowTitle("중앙 업로드")
        self.sync_dialog.status_label.setText("중앙 스프레드시트로 업로드 준비 중...")
        self.sync_dialog.show()

        ws_helper = GoogleWorkspaceSync(key_file, self.drive_folder_id, self.app_dir)
        self.sync_thread = MetadataUploadThread(
            ws_helper,
            self.metadata_sheet_name,
            self.db_path,
            self.sheet_music_path,
            getattr(self, "editor_name", "") or "",
        )

        self.sync_thread.log_signal.connect(self.sync_dialog.append_log)
        self.sync_thread.finished_signal.connect(self.on_db_push_finished)
        self.sync_thread.start()

    def on_db_push_finished(self, success, uploaded_rows, msg):
        self.sync_dialog.finish_sync(success, msg)
        self.sync_dialog.append_log("-" * 30)
        self.sync_dialog.append_log(f"결과: {msg}")
        if success:
            self.sync_dialog.append_log(f"-> {uploaded_rows}건 업로드")
        self.status_bar_label.setText(msg)

    def on_db_sync_finished(self, success, updated_rows, msg):
        self.sync_dialog.finish_sync(success, msg)
        self.sync_dialog.append_log("-" * 30)
        self.sync_dialog.append_log(f"결과: {msg}")
        if success:
            self.sync_dialog.append_log(f"-> {updated_rows}건 반영")
            # 검색/키 필터에 바로 반영
            self.metadata_cache = self.load_all_metadata_from_db()
            self.proxy_model.metadata_cache = self.metadata_cache
            self.proxy_model.invalidate()
            self.load_metadata_to_inspector(self.current_preview_path)
        self.status_bar_label.setText(msg)

    def on_sync_finished(self, success, download_count, msg):  # 인자 구조 변경
        self.sync_dialog.finish_sync(success, msg)
        self.sync_dialog.append_log("-" * 30)
        self.sync_dialog.append_log(f"결과: {msg}")

        if success and download_count > 0:
            self.sync_dialog.append_log(f"-> {download_count}개의 새 악보 저장됨")
            # 파일 목록 갱신
            self.model.setRootPath("")
            self.model.setRootPath(self.sheet_music_path)

        # 기존의 db_updated 체크 및 metadata_cache 갱신 로직 삭제
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
            # 창 크기를 타겟 화면 크기로 설정
            screen_geometry = target_screen.geometry()
            self.viewer.resize(screen_geometry.width(), screen_geometry.height())
            self.viewer.move(target_screen.geometry().topLeft())
            if self.viewer.windowHandle():
                self.viewer.windowHandle().setScreen(target_screen)
        else:
            # 기본 화면 크기로 설정
            if screens:
                primary_screen = screens[0]
                screen_geometry = primary_screen.geometry()
                self.viewer.resize(screen_geometry.width(), screen_geometry.height())
                self.viewer.move(screen_geometry.topLeft())
        
        # 모든 설정이 완료된 후에만 화면에 표시
        self.viewer.setAttribute(Qt.WA_DontShowOnScreen, False)
        self.viewer.setWindowState(Qt.WindowFullScreen)
        self.viewer.show()

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
            # 1. 파일 경로 (이미지) or 텍스트 내용
            path_or_text = item.data(Qt.UserRole)
            # 2. 인터미션 여부
            is_intm = item.data(Qt.UserRole + 1) == True
            # 3. 아이템 타입 (text vs image) - 없으면 image로 간주
            item_type = item.data(Qt.UserRole + 2) or "image"
            # 4. 추가 스타일 정보 (JSON 등)
            extra_info = item.data(Qt.UserRole + 3)

            data.append({
                "path": path_or_text, 
                "is_intermission": is_intm,
                "type": item_type,
                "extra": extra_info
            })
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
        
        # 창을 생성할 때부터 화면 크기로 설정하고 숨김 상태로 유지
        screens = QApplication.screens()
        if screens:
            primary_screen = screens[0]
            screen_geometry = primary_screen.geometry()
            self.resize(screen_geometry.width(), screen_geometry.height())
            self.move(screen_geometry.topLeft())
        
        # 창을 숨긴 상태로 유지 (표시 전까지)
        self.setAttribute(Qt.WA_DontShowOnScreen, True)
        self.hide()

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
        palette.setColor(QPalette.Window, QColor("white"))
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

        # --- [배경색 동적 변경 추가] ---
        bg_color = "black" if is_intermission else "white"
        self.scroll_area.setStyleSheet(f"background-color: {bg_color}; border: none;")
        self.image_label.setStyleSheet(f"background-color: {bg_color};")
        # -----------------------------

        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.image_label.setText("이미지를 불러올 수 없습니다.")
            return

        view_size = self.scroll_area.viewport().size()

        if is_intermission:
            # 화면을 가득 채우되, 비율 유지 + 넘치는 부분 crop
            scaled = pixmap.scaled(
                view_size,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )

            # 중앙 기준으로 crop
            x = (scaled.width() - view_size.width()) // 2
            y = (scaled.height() - view_size.height()) // 2
            cropped = scaled.copy(
                x,
                y,
                view_size.width(),
                view_size.height(),
            )

            self.image_label.setPixmap(cropped)
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
            self.image_label.setPixmap(scaled)
            self.update_next_song_label()

    def get_theme_style(self, theme_name):
        if not theme_name: theme_name = "기본"
        if "새벽" in theme_name:
            return {
                "bg": "background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0f2027, stop:1 #203a43);",
                "color": "#ffffff"
            }
        elif "말씀" in theme_name:
            return {
                "bg": "background-color: #f5f5f0;",
                "color": "#333333"
            }
        elif "은혜" in theme_name:
            return {
                "bg": "background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #23074d, stop:1 #cc5333);",
                "color": "#333333"
            }
        else: # 기본
            return {
                "bg": "background-color: #000000;",
                "color": "#ffffff"
            }

    def load_image(self):
        if not self.playlist_data:
            self.image_label.clear()
            return

        self.zoom = self.initial_zoom
        current_data = self.playlist_data[self.current_index]
        
        path = current_data["path"]
        is_intermission = current_data["is_intermission"]
        item_type = current_data.get("type", "image")
        extra_info = current_data.get("extra", {})

        # --- [TEXT TYPE 처리] ---
        # --- [TEXT TYPE 처리] ---
        if item_type == "text":
            theme = extra_info.get("theme", "기본")
            font_size_input = extra_info.get("font_size", 50) # 기본 50
            font_family = extra_info.get("font_family", "맑은 고딕")
            style = self.get_theme_style(theme)
            
            # 스크롤 영역: 전체 배경
            self.scroll_area.setStyleSheet(f"{style['bg']} border: none;")
            
            # 폰트 크기 계산: 사용자 설정 * 줌 (화면 배율)
            # Full Screen에서는 줌에 따라 카드가 커지거나 글자가 커져야 함.
            # 하지만 카드 디자인이므로, 카드의 크기를 고정하거나 비율로 잡고 안의 글자를 키우는 것이 좋음.
            
            final_font_size = int(font_size_input * self.zoom)

            # 카드 스타일 적용
            card_bg = "background-color: rgba(255, 255, 255, 0.9);"
            border_style = "border: 1px solid #d0d0d0;"
            radius = "border-radius: 20px;" # 더 둥글게
            
            if "Deep Black" in theme or "Midnight" in theme:
                card_bg = "background-color: rgba(0, 0, 0, 0.4);"
                border_style = "border: 1px solid rgba(255, 255, 255, 0.2);"
            
            # 안쪽 여백 및 바깥 여백
            padding = "padding: 60px; margin: 50px;"

            self.image_label.setStyleSheet(f"""
                QLabel {{
                    {card_bg}
                    {border_style}
                    {radius}
                    color: {style['color']};
                    {padding}
                }}
            """)
            
            # 단락 간격 조정을 위해 HTML로 변환
            html_content = ""
            # 윈도우/맥/리눅스 줄바꿈 문자 통일
            safe_text = path.replace("\r\n", "\n").replace("\r", "\n")
            paragraphs = safe_text.split("\n")
            
            for p in paragraphs:
                if not p.strip():
                    # 빈 줄은 시각적 공간 확보 (min-height)
                    html_content += "<p style='margin-bottom: 20px; min-height: 1em;'><br></p>"
                else:
                    # 마진을 통해 단락 간격 확보 (line-height는 기본값 or 1.2 등)
                    # margin-top: 0, margin-bottom: 20px (원하는 간격)
                    html_content += f"<p style='margin-top: 0px; margin-bottom: 30px; line-height: 1.4;'>{p}</p>"
            
            self.image_label.setText(html_content)
            self.image_label.setWordWrap(True)
            
            font = QFont(font_family, final_font_size)
            font.setBold(True)
            self.image_label.setFont(font)
            
            self.image_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            
            # 카드 너비 제약 (화면의 80%) -> 중앙 정렬 효과
            viewport_width = self.scroll_area.viewport().width()
            target_width = int(viewport_width * 0.8)
            self.image_label.setFixedWidth(target_width)
            
            # 높이는 내용에 따라 자동 조절되지만, 화면 적절한 위치에 오도록
            self.image_label.adjustSize()
            
            # Label 자체를 ScrollArea 가운데 정렬
            self.scroll_area.setAlignment(Qt.AlignCenter)
            
            self.update_next_song_label()
            return

        # --- [IMAGE TYPE 처리 (기존 로직)] ---
        # 텍스트 잔재 제거
        self.image_label.setWordWrap(False)

        # --- [배경색 동적 변경 추가] ---
        bg_color = "black" if is_intermission else "white"
        self.scroll_area.setStyleSheet(f"background-color: {bg_color}; border: none;")
        self.image_label.setStyleSheet(f"background-color: {bg_color};")
        # -----------------------------

        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.image_label.setText("이미지를 불러올 수 없습니다.")
            return

        view_size = self.scroll_area.viewport().size()

        if is_intermission:
            # 화면을 가득 채우되, 비율 유지 + 넘치는 부분 crop
            scaled = pixmap.scaled(
                view_size,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )

            # 중앙 기준으로 crop
            x = (scaled.width() - view_size.width()) // 2
            y = (scaled.height() - view_size.height()) // 2
            cropped = scaled.copy(
                x,
                y,
                view_size.width(),
                view_size.height(),
            )

            self.image_label.setPixmap(cropped)
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
        item_type = current_data.get("type", "image")
        extra_info = current_data.get("extra", {})

        # --- [TEXT TYPE 처리] ---
        # --- [TEXT TYPE 처리] ---
        if item_type == "text":
            theme = extra_info.get("theme", "기본")
            font_size_input = extra_info.get("font_size", 50)
            font_family = extra_info.get("font_family", "맑은 고딕")
            style = self.get_theme_style(theme)
            
            self.scroll_area.setStyleSheet(f"{style['bg']} border: none;")
            
            final_font_size = int(font_size_input * self.zoom)

            card_bg = "background-color: rgba(255, 255, 255, 0.9);"
            border_style = "border: 1px solid #d0d0d0;"
            radius = "border-radius: 20px;"
            
            if "Deep Black" in theme or "Midnight" in theme:
                card_bg = "background-color: rgba(0, 0, 0, 0.4);"
                border_style = "border: 1px solid rgba(255, 255, 255, 0.2);"
            
            padding = "padding: 60px; margin: 50px;"

            self.image_label.setStyleSheet(f"""
                QLabel {{
                    {card_bg}
                    {border_style}
                    {radius}
                    color: {style['color']};
                    {padding}
                }}
            """)

            # 단락 간격 조정을 위해 HTML로 변환
            html_content = ""
            safe_text = path.replace("\r\n", "\n").replace("\r", "\n")
            paragraphs = safe_text.split("\n")
            
            for p in paragraphs:
                if not p.strip():
                    html_content += "<p style='margin-bottom: 20px; min-height: 1em;'><br></p>"
                else:
                    html_content += f"<p style='margin-top: 0px; margin-bottom: 30px; line-height: 1.4;'>{p}</p>"

            self.image_label.setText(html_content)
            self.image_label.setWordWrap(True)
            
            font = QFont(font_family, final_font_size)
            font.setBold(True)
            self.image_label.setFont(font)
            self.image_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            
            viewport_width = self.scroll_area.viewport().width()
            target_width = int(viewport_width * 0.8)
            self.image_label.setFixedWidth(target_width)
            self.image_label.adjustSize()
            
            self.scroll_area.setAlignment(Qt.AlignCenter)
            
            self.update_next_song_label()
            return

        # --- [IMAGE TYPE 처리] ---
        self.image_label.setWordWrap(False)

        # --- [배경색 동적 변경 추가] ---
        bg_color = "black" if is_intermission else "white"
        self.scroll_area.setStyleSheet(f"background-color: {bg_color}; border: none;")
        self.image_label.setStyleSheet(f"background-color: {bg_color};")
        # -----------------------------

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
        
        # 텍스트 아이템은 높이 맞춤 기능 제외 (혹은 그냥 리로드)
        current_data = self.playlist_data[self.current_index]
        if current_data.get("type", "image") == "text":
            self.load_image_with_current_zoom()
            return

        path = current_data["path"]
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
            next_data = self.playlist_data[next_index]
            is_intm = next_data["is_intermission"]
            item_type = next_data.get("type", "image")
            
            # [수정] 다음 곡이 인터미션이거나 텍스트 슬라이드면 NEXT 라벨 숨김 (요청사항)
            if is_intm or item_type == "text":
                self.next_song_label.hide()
                return

            path = next_data["path"]
            base_name = os.path.splitext(os.path.basename(path))[0]
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

    # --- [추가] 블랙/로고 모드에서 복귀하는 헬퍼 메서드 ---
    def _return_from_overlay(self):
        """블랙 혹은 로고 화면에서 원래 악보 쇼 화면으로 복귀합니다."""
        if self._is_transitioning:
            return

        def _do_switch():
            self.main_layout.setCurrentWidget(self.scroll_area)
            self.load_image_with_current_zoom()

        # 기존에 구현된 페이드 애니메이션과 함께 복귀
        self._run_brightness_transition(_do_switch)

    # --- [수정] 키 입력 이벤트 핸들러 ---
    def keyPressEvent(self, event):
        # 현재 화면이 블랙 스크린(index 2) 혹은 로고 스크린(index 3)인지 확인
        current_widget = self.main_layout.currentWidget()
        if current_widget in [self.black_screen_widget, self.logo_screen_widget]:
            # Esc 키를 포함하여 어떤 키를 눌러도 쇼 화면으로 복귀합니다.
            self._return_from_overlay()
            return

        # 아래는 기존 로직 유지
        if event.key() == Qt.Key_Escape:
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

        # 페이지 이동 및 기타 제어
        if event.key() in (Qt.Key_PageDown, Qt.Key_Right, Qt.Key_Space):
            if self.current_index < len(self.playlist_data) - 1:
                self._navigate_to(self.current_index + 1)
            else:
                self.show_end_screen()
        elif event.key() in (Qt.Key_PageUp, Qt.Key_Left):
            if self.current_index > 0:
                self._navigate_to(self.current_index - 1)

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

    # --- [수정] 마우스 클릭 이벤트 핸들러 ---
    def mousePressEvent(self, event):
        # 현재 화면이 블랙 혹은 로고 모드인 경우 클릭 시 복귀
        current_widget = self.main_layout.currentWidget()
        if current_widget in [self.black_screen_widget, self.logo_screen_widget]:
            self._return_from_overlay()
            return

        # 아래는 기존 로직 유지
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


# --- [플레이 리스트 곡 통계] 워커 스레드 ---
class PlaylistStatsWorker(QThread):
    """플레이 리스트 폴더를 스캔하여 곡별 등장 통계를 수집합니다. 인터미션 제외."""
    finished = Signal(dict, int)  # song_to_playlists, broken_count
    progress = Signal(str)

    def __init__(self, playlist_path, sheet_music_path, include_subfolders=True):
        super().__init__()
        self.playlist_path = playlist_path
        self.sheet_music_path = sheet_music_path
        self.include_subfolders = include_subfolders

    def _collect_pls_files(self):
        pls_list = []
        if self.include_subfolders:
            for root, _dirs, files in os.walk(self.playlist_path):
                for f in files:
                    if f.lower().endswith(".pls"):
                        full = os.path.join(root, f)
                        rel = os.path.relpath(full, self.playlist_path)
                        pls_list.append((full, rel))
        else:
            try:
                for name in os.listdir(self.playlist_path):
                    p = os.path.join(self.playlist_path, name)
                    if os.path.isfile(p) and name.lower().endswith(".pls"):
                        pls_list.append((p, name))
            except OSError:
                pass
        return pls_list

    def run(self):
        song_to_playlists = {}  # full_path -> set of playlist display names
        broken_count = 0
        pls_list = self._collect_pls_files()
        for i, (pls_path, display_name) in enumerate(pls_list):
            self.progress.emit(f"스캔 중: {display_name}")
            try:
                with open(pls_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(data, list):
                continue
            for entry in data:
                if isinstance(entry, str):
                    path = entry
                    is_intermission = False
                else:
                    path = entry.get("path")
                    is_intermission = entry.get("is_intermission", False)
                if is_intermission:
                    continue
                if not path:
                    continue
                full_path = os.path.normpath(
                    os.path.join(self.sheet_music_path, path)
                )
                if full_path not in song_to_playlists:
                    song_to_playlists[full_path] = set()
                song_to_playlists[full_path].add(display_name)
                if not os.path.isfile(full_path):
                    broken_count += 1
        self.finished.emit(song_to_playlists, broken_count)


# --- [플레이 리스트 곡 통계] 막대 그래프 위젯 ---
class BarChartWidget(QWidget):
    """곡별 등장 횟수를 가로 막대 그래프로 그립니다."""

    barClicked = Signal(str)  # song_name

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = []  # list of (name, count)
        self._max_count = 1
        self.setStyleSheet("background: white;")

    def set_data(self, data):
        """data: list of (song_name, count)"""
        self._data = data
        self._max_count = max((c for _, c in data), default=1)

        # 곡 수에 따라 높이를 늘려 스크롤 영역에서 아래까지 볼 수 있도록 함
        margin_top = 20
        margin_bottom = 20
        bar_height = 22
        gap = 4
        n = len(self._data)
        total_height = margin_top + margin_bottom + max(n, 1) * (bar_height + gap)
        self.setMinimumHeight(total_height)

        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._data:
            painter = QPainter(self)
            painter.drawText(self.rect(), Qt.AlignCenter, "데이터가 없습니다.")
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        r = self.rect()
        margin_left = 120
        margin_right = 40
        margin_top = 20
        margin_bottom = 20
        chart_width = r.width() - margin_left - margin_right

        n = len(self._data)
        if n <= 0:
            return

        bar_height = 22
        gap = 4

        for i, (name, count) in enumerate(self._data):
            y = margin_top + i * (bar_height + gap)
            # 곡명
            text_rect = QRect(4, y, margin_left - 8, bar_height)
            short_name = name if len(name) <= 18 else name[:15] + "..."
            painter.setPen(QColor(0, 0, 0))
            # 제목을 좌측 정렬로 표시
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, short_name)
            # 막대
            bar_x = margin_left
            w = (count / self._max_count) * chart_width if self._max_count else 0
            bar_rect = QRect(int(bar_x), y, int(w), bar_height)
            painter.fillRect(bar_rect, QColor(70, 130, 180))
            painter.setPen(QColor(50, 100, 150))
            painter.drawRect(bar_rect)
            # 횟수
            painter.drawText(
                bar_rect.adjusted(4, 0, 4, 0),
                Qt.AlignLeft | Qt.AlignVCenter,
                str(count),
            )
        painter.end()

    def mousePressEvent(self, event):
        if not self._data:
            return
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        margin_top = 20
        bar_height = 22
        gap = 4
        n = len(self._data)
        for i, (name, _count) in enumerate(self._data):
            y = margin_top + i * (bar_height + gap)
            bar_rect = QRect(0, y, self.width(), bar_height)
            if bar_rect.contains(pos):
                self.barClicked.emit(name)
                break


# --- [플레이 리스트 곡 통계] 다이얼로그 ---
class PlaylistSongStatsDialog(QDialog):
    """곡 기준 플레이 리스트 통계: 요약 카드, 테이블/그래프 탭, 곡 선택 시 포함 리스트 목록."""

    def __init__(self, playlist_path, sheet_music_path, parent=None):
        super().__init__(parent)
        self.playlist_path = playlist_path
        self.sheet_music_path = sheet_music_path
        self.song_to_playlists = {}  # full_path -> set of playlist names
        self.broken_count = 0
        self.include_subfolders = True
        self.setWindowTitle("플레이 리스트 곡 통계")
        self.setMinimumSize(700, 500)
        self.resize(850, 600)
        self._build_ui()
        self._worker = None
        QTimer.singleShot(0, self._start_scan)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # 요약 카드
        cards_layout = QHBoxLayout()
        self.card_songs = QLabel("총 곡 수: -")
        self.card_songs.setStyleSheet(
            "font-weight: bold; font-size: 13pt; padding: 8px;"
        )
        self.card_appearances = QLabel("총 등장 횟수: -")
        self.card_appearances.setStyleSheet(
            "font-weight: bold; font-size: 13pt; padding: 8px;"
        )
        self.card_broken = QLabel("깨진 경로: -")
        self.card_broken.setStyleSheet(
            "font-weight: bold; font-size: 13pt; padding: 8px;"
        )
        cards_layout.addWidget(self.card_songs)
        cards_layout.addWidget(self.card_appearances)
        cards_layout.addWidget(self.card_broken)
        cards_layout.addStretch()
        layout.addLayout(cards_layout)

        # 옵션: Top N, 정렬
        opt_layout = QHBoxLayout()
        opt_layout.addWidget(QLabel("상위 표시:"))
        self.spin_top = QSpinBox()
        self.spin_top.setRange(10, 500)
        self.spin_top.setValue(50)
        self.spin_top.valueChanged.connect(self._refresh_views)
        opt_layout.addWidget(self.spin_top)
        opt_layout.addWidget(QLabel("정렬:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["등장 횟수 내림차순", "곡명 가나다"])
        self.sort_combo.currentIndexChanged.connect(self._refresh_views)
        opt_layout.addWidget(self.sort_combo)
        opt_layout.addStretch()
        layout.addLayout(opt_layout)

        # 탭: 테이블 / 그래프
        self.tab_widget = QTabWidget()
        # 테이블 탭
        table_tab = QWidget()
        table_tab_layout = QVBoxLayout(table_tab)
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["순위", "곡명", "등장 횟수"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        table_tab_layout.addWidget(self.table)
        self.tab_widget.addTab(table_tab, "테이블")
        # 그래프 탭
        graph_tab = QWidget()
        graph_tab_layout = QVBoxLayout(graph_tab)
        self.bar_chart = BarChartWidget()
        self.bar_chart.barClicked.connect(self._on_bar_clicked)
        graph_scroll = QScrollArea()
        graph_scroll.setWidgetResizable(True)
        graph_scroll.setWidget(self.bar_chart)
        graph_tab_layout.addWidget(graph_scroll)
        self.tab_widget.addTab(graph_tab, "그래프")
        layout.addWidget(self.tab_widget)

        # 선택 곡의 포함 리스트 목록
        self.detail_label = QLabel("곡을 선택하면 해당 곡이 포함된 리스트가 표시됩니다.")
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet("padding: 6px; background: #f0f0f0; border-radius: 4px;")
        layout.addWidget(self.detail_label)

        # 진행 표시
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # 버튼
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_refresh = QPushButton("새로 고침")
        self.btn_refresh.clicked.connect(self._start_scan)
        self.btn_close = QPushButton("닫기")
        self.btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_refresh)
        btn_layout.addWidget(self.btn_close)
        layout.addLayout(btn_layout)

    def _start_scan(self):
        self.btn_refresh.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.table.setRowCount(0)
        self.bar_chart.set_data([])
        self.detail_label.setText("스캔 중…")
        self._worker = PlaylistStatsWorker(
            self.playlist_path,
            self.sheet_music_path,
            include_subfolders=self.include_subfolders,
        )
        self._worker.progress.connect(
            lambda t: self.detail_label.setText(t)
        )
        self._worker.finished.connect(self._on_scan_finished)
        self._worker.start()

    def _on_scan_finished(self, song_to_playlists, broken_count):
        self._worker = None
        self.btn_refresh.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.song_to_playlists = song_to_playlists
        self.broken_count = broken_count
        self._update_summary()
        self._refresh_views()
        self.detail_label.setText("곡을 선택하면 해당 곡이 포함된 리스트가 표시됩니다.")

    def _update_summary(self):
        total_songs = len(self.song_to_playlists)
        total_appearances = sum(
            len(plists) for plists in self.song_to_playlists.values()
        )
        self.card_songs.setText(f"총 곡 수: {total_songs}")
        self.card_appearances.setText(f"총 등장 횟수: {total_appearances}")
        self.card_broken.setText(f"깨진 경로: {self.broken_count}")

    def _get_sorted_rows(self):
        """옵션에 따라 정렬된 (name, count, full_path, plists) 리스트 반환."""
        if not self.song_to_playlists:
            return []
        top_n = self.spin_top.value()
        by_count = self.sort_combo.currentIndex() == 0
        rows = []
        for full_path, plists in self.song_to_playlists.items():
            name = os.path.splitext(os.path.basename(full_path))[0]
            count = len(plists)
            rows.append((name, count, full_path, plists))
        if by_count:
            rows.sort(key=lambda x: (-x[1], x[0]))
        else:
            rows.sort(key=lambda x: x[0])
        return rows[:top_n]

    def _refresh_views(self):
        rows = self._get_sorted_rows()
        if not rows:
            self.table.setRowCount(0)
            self.bar_chart.set_data([])
            return
        self.table.setRowCount(len(rows))
        for i, (name, count, full_path, plists) in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.table.setItem(i, 1, QTableWidgetItem(name))
            self.table.setItem(i, 2, QTableWidgetItem(str(count)))
            self.table.item(i, 1).setData(Qt.UserRole, (full_path, plists))
        self.table.clearSelection()
        self.bar_chart.set_data([(name, count) for name, count, _, _ in rows])
        self.detail_label.setText("곡을 선택하면 해당 곡이 포함된 리스트가 표시됩니다.")

    def _on_bar_clicked(self, song_name: str):
        """그래프 막대를 클릭했을 때 해당 곡의 리스트 정보를 표시합니다."""
        rows = self._get_sorted_rows()
        target_row = -1
        plists = None
        for i, (name, _count, _full_path, pls) in enumerate(rows):
            if name == song_name:
                target_row = i
                plists = pls
                break
        if target_row >= 0 and plists is not None:
            # 테이블 선택도 동기화
            if self.table.rowCount() > target_row:
                self.table.selectRow(target_row)
            names = sorted(plists)
            text = "이 곡이 포함된 리스트 (" + str(len(names)) + "개):\n" + "\n".join(
                "  • " + n for n in names
            )
            self.detail_label.setText(text)

    def _on_selection_changed(self):
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 1)
        if not item:
            return
        data = item.data(Qt.UserRole)
        if not data:
            return
        _full_path, plists = data
        names = sorted(plists)
        text = "이 곡이 포함된 리스트 (" + str(len(names)) + "개):\n" + "\n".join(
            "  • " + n for n in names
        )
        self.detail_label.setText(text)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 폰트 등 기타 설정이 있다면 이 부분에 유지

    window = PraiseSheetViewer()

    # [수정] 화면 크기를 1800, 900으로 설정
    window.resize(1800, 900)

    # 전체 화면(showMaximized) 대신 일반 모드(show)로 실행
    window.show()

    sys.exit(app.exec())
