#!/usr/bin/env python3
"""Build a LiveContainer/AltStore source from upstream GitHub releases."""

from __future__ import annotations

import concurrent.futures
import json
import os
import plistlib
import re
import shutil
import struct
import tempfile
import time
import urllib.request
import zipfile
import zlib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "apps.json"
ICON_DIR = ROOT / "assets" / "icons"
SOURCE_REPOSITORY = os.environ.get(
    "SOURCE_REPOSITORY",
    os.environ.get("GITHUB_REPOSITORY", "Ruawd/livecontainer_source"),
)
SOURCE_BRANCH = os.environ.get("SOURCE_BRANCH", "main")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
USER_AGENT = f"{SOURCE_REPOSITORY} AltSource updater"
MAX_WORKERS = max(1, int(os.environ.get("UPDATE_WORKERS", "2")))
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

APPS = [
    {
        "name": "FluxDO",
        "developerName": "Lingyan000",
        "repository": "Lingyan000/fluxdo",
        "assetPattern": r"^fluxdo-unsigned\.ipa$",
        "subtitle": "一个 Linux.do 第三方客户端",
        "tintColor": "#2F80ED",
        "iconName": "fluxdo.png",
    },
    {
        "name": "Jasmine",
        "developerName": "ComicSparks",
        "repository": "ComicSparks/jasmine",
        "assetPattern": r"^jasmine-v.+-nosign\.ipa$",
        "subtitle": "支持多平台的漫画阅读器",
        "tintColor": "#8B5CF6",
        "iconName": "jasmine.png",
    },
    {
        "name": "Pikapika",
        "developerName": "ComicSparks",
        "repository": "ComicSparks/pikapika",
        "assetPattern": r"^pikapika-v.+-ios_nosign-.+\.ipa$",
        "subtitle": "支持多平台的漫画阅读器",
        "tintColor": "#EC4899",
        "iconName": "pikapika.png",
    },
    {
        "name": "Asspp",
        "developerName": "Lakr Aream",
        "repository": "Lakr233/Asspp",
        "assetPattern": r"^Asspp\.ipa$",
        "subtitle": "多账号、跨地区的 App Store 管理工具",
        "tintColor": "#F59E0B",
        "iconName": "asspp.png",
    },
    {
        "name": "Kazumi",
        "developerName": "Predidit",
        "repository": "Predidit/Kazumi",
        "assetPattern": r"^Kazumi_ios_.+_no_sign\.ipa$",
        "subtitle": "基于自定义规则的番剧采集与在线观看工具",
        "tintColor": "#10B981",
        "iconName": "kazumi.png",
    },
    {
        "name": "SyncClipboard",
        "developerName": "Ruawd",
        "repository": "Ruawd/SyncClipboard-iOS",
        "assetPattern": r"^SyncClipboard-iOS26-unsigned\.ipa$",
        "subtitle": "原生 SwiftUI SyncClipboard 客户端",
        "tintColor": "#4F8EF7",
        "iconName": "syncclipboard.png",
    },
    {
        "name": "Orange Cloud",
        "developerName": "Ruawd / chen2he",
        "repository": "Ruawd/orange-cloud",
        "assetPattern": r"^OrangeCloud-OpenSourceUnlocked-unsigned\.ipa$",
        "subtitle": "原生 Cloudflare 管理客户端（开源解锁版）",
        "tintColor": "#F97316",
        "iconName": "orange-cloud.png",
    },
    {
        "name": "KMusic（歌一刀）",
        "developerName": "Mac-XK",
        "repository": "Mac-XK/KMusic",
        "assetPattern": r"^.+\.ipa$",
        "subtitle": "基于 SwiftUI 的多源音乐聚合播放器",
        "tintColor": "#7C3AED",
        "iconName": "kmusic.png",
    },
    {
        "name": "LK",
        "developerName": "LK",
        "repository": "Ruawd/livecontainer_source",
        "assetPattern": r"^LK-[0-9].*\.ipa$",
        "subtitle": "LK iOS 客户端",
        "tintColor": "#16A34A",
        "iconName": "lk.png",
    },
]


def request_json(url: str) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    last_error = ""
    for attempt in range(1, 5):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.load(response)
        except Exception as error:  # noqa: BLE001 - retry transient GitHub API failures.
            last_error = str(error)
            if attempt < 4:
                time.sleep(2**attempt)
    raise RuntimeError(f"GitHub API 请求失败：{last_error}")


def download_file(url: str, destination: Path, expected_size: int) -> None:
    last_error = ""
    for attempt in range(1, 5):
        separator = "&" if "?" in url else "?"
        attempt_url = f"{url}{separator}download=1&altsource_retry={attempt}"
        request = urllib.request.Request(
            attempt_url,
            headers={
                "Accept": "application/octet-stream",
                "Cache-Control": "no-cache",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                with destination.open("wb") as output:
                    shutil.copyfileobj(response, output)
            actual_size = destination.stat().st_size
            if actual_size == expected_size and zipfile.is_zipfile(destination):
                return
            with destination.open("rb") as downloaded:
                signature = downloaded.read(32)
            last_error = (
                f"文件不完整（{actual_size}/{expected_size} 字节，"
                f"文件头 {signature!r}）"
            )
        except Exception as error:  # noqa: BLE001 - retry transient CDN errors.
            last_error = str(error)
        if attempt < 4:
            print(f"下载校验失败，准备第 {attempt + 1} 次尝试：{last_error}", flush=True)
            time.sleep(2**attempt)
    raise RuntimeError(f"下载 IPA 失败：{last_error}")


def find_release_and_asset(
    releases: list[dict[str, Any]], pattern: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    asset_pattern = re.compile(pattern, re.IGNORECASE)
    for release in releases:
        if release.get("draft") or release.get("prerelease"):
            continue
        for asset in release.get("assets", []):
            if asset_pattern.fullmatch(asset.get("name", "")):
                return release, asset
    raise RuntimeError("找不到带有匹配 IPA 的稳定 Release")


def primary_info_plist(archive: zipfile.ZipFile) -> str:
    candidates = [
        name
        for name in archive.namelist()
        if re.fullmatch(r"Payload/[^/]+\.app/Info\.plist", name)
    ]
    if not candidates:
        raise RuntimeError("IPA 中找不到主应用 Info.plist")
    return min(candidates, key=len)


def icon_file_names(info: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for key in ("CFBundleIconFiles",):
        value = info.get(key, [])
        if isinstance(value, list):
            names.update(str(item).lower() for item in value)

    for key in ("CFBundleIcons", "CFBundleIcons~ipad"):
        icons = info.get(key, {})
        if not isinstance(icons, dict):
            continue
        primary = icons.get("CFBundlePrimaryIcon", {})
        if not isinstance(primary, dict):
            continue
        value = primary.get("CFBundleIconFiles", [])
        if isinstance(value, list):
            names.update(str(item).lower() for item in value)
    return names


def png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    if not data.startswith(PNG_SIGNATURE):
        return []
    chunks = []
    offset = len(PNG_SIGNATURE)
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_data = data[offset + 8 : offset + 8 + length]
        if len(chunk_data) != length:
            raise RuntimeError("PNG 数据不完整")
        chunks.append((chunk_type, chunk_data))
        offset += 12 + length
        if chunk_type == b"IEND":
            break
    return chunks


def paeth_predictor(left: int, above: int, upper_left: int) -> int:
    value = left + above - upper_left
    left_distance = abs(value - left)
    above_distance = abs(value - above)
    upper_left_distance = abs(value - upper_left)
    if left_distance <= above_distance and left_distance <= upper_left_distance:
        return left
    if above_distance <= upper_left_distance:
        return above
    return upper_left


def unfilter_scanlines(
    filtered: bytes, width: int, height: int, bytes_per_pixel: int
) -> list[bytearray]:
    row_length = width * bytes_per_pixel
    expected_length = height * (row_length + 1)
    if len(filtered) != expected_length:
        raise RuntimeError(
            f"CgBI 像素数据长度异常：{len(filtered)}/{expected_length}"
        )

    rows: list[bytearray] = []
    offset = 0
    previous = bytearray(row_length)
    for _ in range(height):
        filter_type = filtered[offset]
        offset += 1
        encoded = filtered[offset : offset + row_length]
        offset += row_length
        decoded = bytearray(row_length)

        for index, value in enumerate(encoded):
            left = decoded[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            above = previous[index]
            upper_left = (
                previous[index - bytes_per_pixel]
                if index >= bytes_per_pixel
                else 0
            )
            if filter_type == 0:
                decoded[index] = value
            elif filter_type == 1:
                decoded[index] = (value + left) & 0xFF
            elif filter_type == 2:
                decoded[index] = (value + above) & 0xFF
            elif filter_type == 3:
                decoded[index] = (value + ((left + above) // 2)) & 0xFF
            elif filter_type == 4:
                decoded[index] = (
                    value + paeth_predictor(left, above, upper_left)
                ) & 0xFF
            else:
                raise RuntimeError(f"不支持的 PNG 过滤器：{filter_type}")
        rows.append(decoded)
        previous = decoded
    return rows


def make_png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(chunk_type)
    checksum = zlib.crc32(data, checksum) & 0xFFFFFFFF
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", checksum)
    )


def normalize_png(data: bytes) -> bytes:
    """Convert Apple's CgBI-optimized PNG data into a standard RGBA PNG."""

    chunks = png_chunks(data)
    if not chunks or not any(chunk_type == b"CgBI" for chunk_type, _ in chunks):
        return data

    ihdr = next(
        (chunk_data for chunk_type, chunk_data in chunks if chunk_type == b"IHDR"),
        None,
    )
    if ihdr is None or len(ihdr) != 13:
        raise RuntimeError("CgBI PNG 缺少有效的 IHDR")
    width, height, bit_depth, color_type, compression, filtering, interlace = (
        struct.unpack(">IIBBBBB", ihdr)
    )
    if (
        bit_depth != 8
        or color_type != 6
        or compression != 0
        or filtering != 0
        or interlace != 0
    ):
        raise RuntimeError("暂不支持此 CgBI PNG 像素格式")

    compressed = b"".join(
        chunk_data for chunk_type, chunk_data in chunks if chunk_type == b"IDAT"
    )
    filtered = zlib.decompress(compressed, -15)
    rows = unfilter_scanlines(filtered, width, height, 4)

    output_rows = bytearray()
    for row in rows:
        output_rows.append(0)
        for offset in range(0, len(row), 4):
            blue, green, red, alpha = row[offset : offset + 4]
            if alpha:
                red = min(255, (red * 255 + alpha // 2) // alpha)
                green = min(255, (green * 255 + alpha // 2) // alpha)
                blue = min(255, (blue * 255 + alpha // 2) // alpha)
            output_rows.extend((red, green, blue, alpha))

    return (
        PNG_SIGNATURE
        + make_png_chunk(b"IHDR", ihdr)
        + make_png_chunk(b"IDAT", zlib.compress(bytes(output_rows), level=9))
        + make_png_chunk(b"IEND", b"")
    )


def extract_metadata_and_icon(ipa_path: Path) -> tuple[dict[str, str], bytes | None]:
    with zipfile.ZipFile(ipa_path) as archive:
        plist_path = primary_info_plist(archive)
        info = plistlib.loads(archive.read(plist_path))
        app_prefix = plist_path.removesuffix("Info.plist")
        declared_icons = icon_file_names(info)

        root_pngs = []
        for item in archive.infolist():
            if not item.filename.startswith(app_prefix):
                continue
            relative_name = item.filename[len(app_prefix) :]
            if "/" in relative_name or not relative_name.lower().endswith(".png"):
                continue
            root_pngs.append(item)

        declared_candidates = [
            item
            for item in root_pngs
            if any(
                item.filename[len(app_prefix) :].lower().removesuffix(".png").startswith(name)
                for name in declared_icons
            )
        ]
        fallback_candidates = [
            item
            for item in root_pngs
            if "appicon" in item.filename.lower() or "icon" in item.filename.lower()
        ]
        candidates = declared_candidates or fallback_candidates
        icon_bytes = (
            normalize_png(
                archive.read(max(candidates, key=lambda item: item.file_size))
            )
            if candidates
            else None
        )

    metadata = {
        "bundleIdentifier": str(info.get("CFBundleIdentifier", "")),
        "version": str(info.get("CFBundleShortVersionString", "")),
        "buildVersion": str(info.get("CFBundleVersion", "")),
        "minOSVersion": str(info.get("MinimumOSVersion", "")),
    }
    if not metadata["bundleIdentifier"]:
        raise RuntimeError("IPA 的 Info.plist 缺少 CFBundleIdentifier")
    return metadata, icon_bytes


def load_existing_apps() -> dict[str, dict[str, Any]]:
    if not OUTPUT_PATH.exists():
        return {}
    try:
        source = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        app["sourceRepository"]: app
        for app in source.get("apps", [])
        if isinstance(app, dict) and app.get("sourceRepository")
    }


def normalized_release_notes(release: dict[str, Any], fallback: str) -> str:
    notes = (release.get("body") or release.get("name") or fallback).strip()
    return notes[:8000]


def version_entry(
    metadata: dict[str, str],
    release: dict[str, Any],
    asset: dict[str, Any],
    description: str,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "version": metadata["version"],
        "buildVersion": metadata["buildVersion"],
        # LiveContainer currently reads this legacy spelling for the displayed build.
        "buildNumber": metadata["buildVersion"],
        "date": release["published_at"],
        "localizedDescription": normalized_release_notes(release, description),
        "downloadURL": asset["browser_download_url"],
        "size": int(asset["size"]),
    }
    if metadata["minOSVersion"]:
        entry["minOSVersion"] = metadata["minOSVersion"]
    return entry


def merged_version_history(
    latest: dict[str, Any], existing_app: dict[str, Any] | None
) -> list[dict[str, Any]]:
    versions = [latest]
    seen = {latest["downloadURL"]}
    for version in (existing_app or {}).get("versions", []):
        url = version.get("downloadURL")
        if not url or url in seen:
            continue
        versions.append(version)
        seen.add(url)
        if len(versions) >= 10:
            break
    return versions


def process_app(
    config: dict[str, str], existing_app: dict[str, Any] | None
) -> tuple[dict[str, Any], bytes | None]:
    repository = config["repository"]
    repo_info = request_json(f"https://api.github.com/repos/{repository}")
    releases = request_json(
        f"https://api.github.com/repos/{repository}/releases?per_page=20"
    )
    release, asset = find_release_and_asset(releases, config["assetPattern"])

    existing_latest = ((existing_app or {}).get("versions") or [{}])[0]
    same_asset = existing_latest.get("downloadURL") == asset["browser_download_url"]
    icon_path = ICON_DIR / config["iconName"]

    icon_bytes: bytes | None = None
    if same_asset and existing_app and icon_path.exists():
        metadata = {
            "bundleIdentifier": str(existing_app["bundleIdentifier"]),
            "version": str(existing_latest["version"]),
            "buildVersion": str(
                existing_latest.get("buildVersion")
                or existing_latest.get("buildNumber")
                or ""
            ),
            "minOSVersion": str(existing_latest.get("minOSVersion") or ""),
        }
        current_icon = icon_path.read_bytes()
        normalized_icon = normalize_png(current_icon)
        if normalized_icon != current_icon:
            icon_bytes = normalized_icon
    else:
        with tempfile.NamedTemporaryFile(suffix=".ipa", delete=False) as temp_file:
            temp_path = Path(temp_file.name)
        try:
            print(f"下载 {config['name']} {release['tag_name']}…", flush=True)
            download_file(
                asset["browser_download_url"],
                temp_path,
                int(asset["size"]),
            )
            metadata, icon_bytes = extract_metadata_and_icon(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)

    description = (
        repo_info.get("description")
        or config["subtitle"]
        or f"{config['name']} 的 GitHub Release"
    )
    latest = version_entry(metadata, release, asset, description)
    versions = merged_version_history(latest, existing_app)
    raw_base = (
        f"https://raw.githubusercontent.com/{SOURCE_REPOSITORY}/"
        f"{SOURCE_BRANCH}/assets/icons"
    )

    app: dict[str, Any] = {
        "name": config["name"],
        "bundleIdentifier": metadata["bundleIdentifier"],
        "developerName": config["developerName"],
        "subtitle": config["subtitle"],
        "localizedDescription": description,
        "version": metadata["version"],
        "versionDate": release["published_at"],
        "versionDescription": latest["localizedDescription"],
        "downloadURL": asset["browser_download_url"],
        "size": int(asset["size"]),
        "iconURL": f"{raw_base}/{config['iconName']}",
        "tintColor": config["tintColor"],
        "sourceRepository": repository,
        "versions": versions,
    }
    return app, icon_bytes


def write_if_changed(path: Path, content: bytes) -> bool:
    if path.exists() and path.read_bytes() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return True


def main() -> None:
    existing_apps = load_existing_apps()
    results: dict[str, tuple[dict[str, Any], bytes | None]] = {}
    failures: list[str] = []

    # GitHub's release CDN can throttle many simultaneous large IPA downloads.
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_app, config, existing_apps.get(config["repository"])): config
            for config in APPS
        }
        for future in concurrent.futures.as_completed(futures):
            config = futures[future]
            try:
                results[config["repository"]] = future.result()
            except Exception as error:  # noqa: BLE001 - preserve an existing entry on network failures.
                existing = existing_apps.get(config["repository"])
                if existing:
                    print(
                        f"警告：更新 {config['name']} 失败，保留原数据：{error}",
                        flush=True,
                    )
                    results[config["repository"]] = (existing, None)
                else:
                    failures.append(f"{config['name']}: {error}")

    if failures:
        raise RuntimeError("首次生成失败：" + "；".join(failures))

    apps = []
    icons_changed = False
    for config in APPS:
        app, icon_bytes = results[config["repository"]]
        apps.append(app)
        if icon_bytes:
            icons_changed |= write_if_changed(ICON_DIR / config["iconName"], icon_bytes)

    source = {
        "name": "Ruawd LiveContainer Source",
        "identifier": "com.ruawd.livecontainer.source",
        "subtitle": "自动跟踪 GitHub Releases 中的最新 IPA",
        "description": "每 15 分钟检查上游项目，并自动更新到最新稳定版本。",
        "website": f"https://github.com/{SOURCE_REPOSITORY}",
        "tintColor": "#0A84FF",
        "apps": apps,
    }
    source_content = (
        json.dumps(source, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    source_changed = write_if_changed(OUTPUT_PATH, source_content)

    if source_changed or icons_changed:
        print("软件源已更新。")
    else:
        print("已是最新版本，无需修改。")


if __name__ == "__main__":
    main()
