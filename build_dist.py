"""배포판 빌드 스크립트.

musicsheetviewer(뷰어)와 sheetcapture(악보수집도구)를 각각 PyInstaller로 빌드한 뒤,
sheetcapture를 뷰어 배포 폴더 안에 합치고, 공유해야 하는 파일(service_account.json,
song_metadata.db)만 넣고 개인/로컬 전용 파일(settings.json, song_titles.db)은 절대
포함되지 않도록 정리해서 dist/musicsheetviewer.zip으로 압축합니다.

사용법: (프로젝트 루트에서, venv 활성화 상태로)
    python build_dist.py

공유 정책 (변경 시 이 스크립트도 함께 검토할 것):
- 악보 / 가사·키 DB: service_account.json + drive_folder_id로 구글 드라이브를 통해
  모든 설치본이 공유 (코드의 load_settings 기본값 참고).
- 찬양 리스트(플레이리스트): 공유하지 않음. settings.json을 배포판에 넣지 않아야
  playlist_sheet_id가 빈 값(기본값)으로 시작해서 자동으로는 공유되지 않음.
- 곡 제목 오버레이(song_titles.db): PC별 로컬 전용. 배포판에 넣지 않음(넣으면 설치
  시점의 값으로 사용자 로컬 데이터가 덮어써질 수 있음).
"""

import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
VIEWER_DIST = os.path.join(DIST, "musicsheetviewer")
CAPTURE_DIST = os.path.join(DIST, "sheetcapture")

# 배포판에 반드시 포함되어야 하는, 모든 설치본이 공유하는 파일
SHARED_FILES = ["service_account.json", "song_metadata.db"]

# 배포판에 절대 포함되면 안 되는, PC별/사람별 로컬 전용 파일
LOCAL_ONLY_FILES = ["settings.json", "song_titles.db"]


def run_pyinstaller(spec_name: str) -> None:
    print(f"\n=== PyInstaller 빌드: {spec_name} ===")
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", spec_name, "--clean", "-y"],
        cwd=ROOT,
        check=True,
    )


def merge_capture_tool_into_viewer() -> None:
    print("\n=== 악보수집도구를 뷰어 배포 폴더에 합치는 중 ===")
    src_exe = os.path.join(CAPTURE_DIST, "sheetcapture.exe")
    src_libdir = os.path.join(CAPTURE_DIST, "lib_capture")
    if not os.path.isfile(src_exe) or not os.path.isdir(src_libdir):
        raise RuntimeError(
            f"sheetcapture 빌드 결과를 찾을 수 없습니다: {CAPTURE_DIST}"
        )

    dst_libdir = os.path.join(VIEWER_DIST, "lib_capture")
    if os.path.isdir(dst_libdir):
        shutil.rmtree(dst_libdir)
    shutil.copytree(src_libdir, dst_libdir)
    shutil.copy2(src_exe, os.path.join(VIEWER_DIST, "sheetcapture.exe"))

    # 합친 뒤에는 독립된 sheetcapture 배포 폴더는 필요 없음
    shutil.rmtree(CAPTURE_DIST)


def add_shared_files() -> None:
    print("\n=== 공유 파일(악보/가사DB 접근용) 추가 ===")
    for name in SHARED_FILES:
        src = os.path.join(ROOT, name)
        if not os.path.isfile(src):
            print(f"  [경고] '{name}'이(가) 프로젝트 루트에 없어 건너뜁니다: {src}")
            continue
        shutil.copy2(src, os.path.join(VIEWER_DIST, name))
        print(f"  포함됨: {name}")


def strip_local_only_files() -> None:
    print("\n=== 로컬 전용 파일 제외 확인 ===")
    for name in LOCAL_ONLY_FILES:
        path = os.path.join(VIEWER_DIST, name)
        if os.path.exists(path):
            os.remove(path)
            print(f"  제거됨(정책상 배포 금지): {name}")
        else:
            print(f"  확인됨(포함 안 됨): {name}")


def make_zip() -> str:
    print("\n=== ZIP 압축 중 ===")
    zip_base = os.path.join(DIST, "musicsheetviewer")
    zip_path = zip_base + ".zip"
    if os.path.exists(zip_path):
        os.remove(zip_path)
    shutil.make_archive(zip_base, "zip", root_dir=DIST, base_dir="musicsheetviewer")
    return zip_path


def verify(zip_path: str) -> None:
    print("\n=== 검증 ===")
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
    leaked = [n for n in names if any(local in n for local in LOCAL_ONLY_FILES)]
    if leaked:
        raise RuntimeError(f"로컬 전용 파일이 배포판에 포함되었습니다: {leaked}")
    missing = [
        n
        for n in SHARED_FILES
        if not any(name.endswith(f"musicsheetviewer/{n}") for name in names)
    ]
    if missing:
        print(f"  [경고] 공유 파일이 배포판에 없습니다: {missing}")
    print(f"  OK: 로컬 전용 파일 없음, 총 {len(names)}개 항목")
    size_mb = os.path.getsize(zip_path) / (1024 * 1024)
    print(f"  결과물: {zip_path} ({size_mb:.1f} MB)")


def main() -> None:
    run_pyinstaller("musicsheetviewer.spec")
    run_pyinstaller("sheetcapture.spec")
    merge_capture_tool_into_viewer()
    add_shared_files()
    strip_local_only_files()
    zip_path = make_zip()
    verify(zip_path)
    print("\n배포판 빌드 완료.")


if __name__ == "__main__":
    main()
