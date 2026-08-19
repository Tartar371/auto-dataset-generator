"""Upload the daily zip to a dedicated Gumroad product (presign → S3 PUT → complete → attach)."""

from __future__ import annotations

import logging
import os
import uuid
import zipfile
from pathlib import Path
from typing import Any

from pipeline.http import HttpError, fetch_json, post_form_json, put_raw, send_json

log = logging.getLogger("pipeline.gumroad")
API = "https://api.gumroad.com/v2"
ZIP_NAMES = ("bundle.json", "crypto_markets.csv", "report.md")
DATASET_PRODUCT_NAME = "Daily Market & Tech Dataset"
FILE_CLIENT_ID = "daily-latest"


def zip_daily_artifacts(day_dir: Path, day: str) -> Path:
    zip_path = day_dir / f"daily-market-dataset-{day}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ZIP_NAMES:
            source = day_dir / name
            if source.exists():
                archive.write(source, arcname=name)
    if zip_path.stat().st_size < 32:
        raise RuntimeError(f"Gumroad zip is empty: {zip_path}")
    return zip_path


def _require_success(payload: Any, action: str) -> dict[str, Any]:
    if not isinstance(payload, dict) or not payload.get("success"):
        raise HttpError(f"Gumroad {action} failed: {payload}")
    return payload


def _auth_payload(access_token: str, extra: dict[str, Any]) -> dict[str, Any]:
    body = {"access_token": access_token}
    body.update(extra)
    return body


def upload_file(access_token: str, zip_path: Path) -> str:
    size = zip_path.stat().st_size
    presign = _require_success(
        post_form_json(
            f"{API}/files/presign",
            {
                "access_token": access_token,
                "filename": zip_path.name,
                "file_size": str(size),
            },
        ),
        "presign",
    )
    parts = presign.get("parts") or []
    if not parts:
        raise HttpError("Gumroad presign returned no parts")
    if len(parts) != 1:
        raise HttpError(f"Gumroad zip split into {len(parts)} parts; daily zip should be one part")

    headers = put_raw(parts[0]["presigned_url"], zip_path.read_bytes())
    etag = headers.get("etag") or headers.get("ETag")
    if not etag:
        raise HttpError(f"S3 PUT missing ETag headers={headers}")

    completed = _require_success(
        post_form_json(
            f"{API}/files/complete",
            {
                "access_token": access_token,
                "upload_id": str(presign["upload_id"]),
                "key": str(presign["key"]),
                "parts[][part_number]": "1",
                "parts[][etag]": etag,
            },
        ),
        "complete",
    )
    file_url = completed.get("file_url") or presign.get("file_url")
    if not file_url:
        raise HttpError("Gumroad complete did not return file_url")
    return str(file_url)


def list_products(access_token: str) -> list[dict[str, Any]]:
    payload = fetch_json(f"{API}/products?access_token={access_token}")
    products = payload.get("products") if isinstance(payload, dict) else None
    return list(products or [])


def ensure_dataset_product(access_token: str, requested_id: str | None = None) -> dict[str, Any]:
    """Use a dedicated dataset product. Never overwrite unrelated listings."""
    products = list_products(access_token)
    for product in products:
        if (product.get("name") or "") == DATASET_PRODUCT_NAME:
            log.info("using existing Gumroad product %s", product.get("id"))
            return product
    if requested_id:
        match = next((p for p in products if p.get("id") == requested_id), None)
        if match and (match.get("name") or "") == DATASET_PRODUCT_NAME:
            return match
        if match:
            log.warning(
                "GUMROAD_PRODUCT_ID points at %r (%s); creating a separate dataset product instead",
                match.get("name"),
                requested_id,
            )
    created = _require_success(
        send_json(
            f"{API}/products",
            _auth_payload(
                access_token,
                {
                    "native_type": "digital",
                    "name": DATASET_PRODUCT_NAME,
                    "price": 900,
                    "description": (
                        "Daily CSV/JSON market & tech briefing from public APIs. "
                        "Research data, not financial advice."
                    ),
                },
            ),
        ),
        "create product",
    )
    product = created.get("product") or created
    log.info("created Gumroad product %s", product.get("id"))
    return product


def _assert_safe_target(existing: dict[str, Any] | None) -> None:
    if not existing:
        return
    name = existing.get("name") or ""
    if name == DATASET_PRODUCT_NAME:
        return
    raise HttpError(
        f"Refusing to replace files on Gumroad product {existing.get('id')!r} named {name!r}. "
        f"Create or point GUMROAD_PRODUCT_ID at '{DATASET_PRODUCT_NAME}'."
    )


def attach_file(
    access_token: str,
    product_id: str,
    file_url: str,
    *,
    name: str,
    description: str,
    day: str,
) -> None:
    product = fetch_json(f"{API}/products/{product_id}?access_token={access_token}")
    existing = (product or {}).get("product") if isinstance(product, dict) else None
    _assert_safe_target(existing)
    payload = _auth_payload(
        access_token,
        {
            "name": (existing or {}).get("name") or name,
            "description": description,
            "files": [{"url": file_url, "external_id": FILE_CLIENT_ID}],
            "rich_content": [
                {
                    "description": {
                        "type": "doc",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": f"Latest drop: daily-market-dataset-{day}.zip",
                                    }
                                ],
                            },
                            {
                                "type": "fileEmbed",
                                "attrs": {
                                    "id": FILE_CLIENT_ID,
                                    "uid": str(uuid.uuid4()),
                                    "collapsed": False,
                                },
                            },
                        ],
                    }
                }
            ],
        },
    )
    price = (existing or {}).get("price")
    if price is not None:
        payload["price"] = price
    _require_success(send_json(f"{API}/products/{product_id}", payload, method="PUT"), "attach")


def write_product_id(env_path: Path, product_id: str) -> None:
    if not env_path.is_file():
        return
    lines = []
    found = False
    for line in env_path.read_text(encoding="utf-8").splitlines(True):
        if line.startswith("GUMROAD_PRODUCT_ID="):
            lines.append(f"GUMROAD_PRODUCT_ID={product_id}\n")
            found = True
        else:
            lines.append(line)
    if not found:
        lines.append(f"GUMROAD_PRODUCT_ID={product_id}\n")
    env_path.write_text("".join(lines), encoding="utf-8")
    os.environ["GUMROAD_PRODUCT_ID"] = product_id


def publish_daily_zip(
    access_token: str,
    product_id: str,
    day_dir: Path,
    bundle: dict[str, Any],
    summary: str,
    env_path: Path | None = None,
) -> Path:
    day = str(bundle.get("date") or day_dir.name)
    product = ensure_dataset_product(access_token, product_id)
    target_id = str(product.get("id") or product_id)
    if env_path:
        write_product_id(env_path, target_id)
    zip_path = zip_daily_artifacts(day_dir, day)
    log.info("uploading %s (%s bytes) to Gumroad product %s", zip_path.name, zip_path.stat().st_size, target_id)
    file_url = upload_file(access_token, zip_path)
    description = (
        f"Daily market & tech dataset for {day}. Research data, not financial advice.\n\n"
        + summary[:1500]
    )
    attach_file(
        access_token,
        target_id,
        file_url,
        name=DATASET_PRODUCT_NAME,
        description=description,
        day=day,
    )
    log.info("Gumroad product file replaced with %s", zip_path.name)
    return zip_path
