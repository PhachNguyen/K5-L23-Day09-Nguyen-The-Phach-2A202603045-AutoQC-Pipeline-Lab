"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |

Bẫy cần nghĩ tới (có test cho từng cái)
- Một file có NHIỀU dòng lỗi: số dòng trong `issues` là số dòng GỐC. Nếu xoá từng dòng một thì số dòng lệch.
  Gom theo file, rồi ghi lại MỘT lần.
- Sau khi cắt, box có thể không còn diện tích (nằm hẳn ngoài ảnh): lúc đó xoá dòng thay vì ghi box rỗng.
- Một dòng có 2 lỗi (vd. BOX_OUT_OF_IMAGE + DUP_BOX): xoá dòng thắng, chỉ ghi 1 fix `drop_line`, không ghi thêm `clip_box`. Dòng trống ở giữa file vẫn đếm vào số dòng gốc.
- Ảnh vừa bị xoá (DUP_IMAGE_*...) mà còn issue dòng của chính nó: bỏ qua êm, không được báo lỗi/chết.
- Không động tới lỗi WARN (cảnh báo là việc của người). Không sửa file ở `data/raw/` — chỉ sửa `ds`.
- Chạy lần 2 trên dữ liệu đã sửa phải không làm gì thêm (idempotent) — NGOẠI LỆ duy nhất: `needs_label` được ghi lại mỗi lần còn lỗi `MISSING_LABEL_FILE` (vì ảnh vẫn chưa có nhãn).

- `needs_label` KHÔNG tạo file nhãn rỗng (rỗng = "ảnh nền", khác với "chưa gán"). `review_queue` sẽ đẩy ảnh này lên đầu hàng đợi cho người.

Gợi ý: `yaml.safe_load / safe_dump`.
"""
from collections import defaultdict  # noqa: F401

import yaml  # noqa: F401

from ..common import ERROR, parse_yolo_line  # noqa: F401


def fix(ds, issues, cfg):
    drop_codes = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}
    remove_codes = {"LEAK_TEST", "CORRUPT_IMAGE", "BAD_SIZE"}
    errors = [issue for issue in issues if issue.severity == ERROR]
    fixes = []

    remove_stems = {
        issue.image for issue in errors
        if issue.code.startswith("DUP_IMAGE_") or issue.code in remove_codes
    }
    for stem in sorted(remove_stems):
        image_path = ds.image_path(stem)
        label_path = ds.label_path(stem)
        if image_path is None and not label_path.exists():
            continue
        if image_path is not None:
            image_path.unlink()
        label_path.unlink(missing_ok=True)
        fixes.append({
            "image": stem, "line": None, "action": "remove_image",
            "before": "ảnh và nhãn trong ds", "after": "đã xóa khỏi ds",
        })

    if any(issue.code == "BAD_CLASS_NAME" for issue in errors):
        data = yaml.safe_load(ds.yaml_path.read_text(encoding="utf-8")) if ds.yaml_path.exists() else {}
        if data is None:
            data = {}
        before = str(data.get("names", "(không có names)"))
        data["names"] = cfg["classes"]
        ds.yaml_path.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        fixes.append({
            "image": "data.yaml", "line": None, "action": "rename_classes",
            "before": before, "after": str(cfg["classes"]),
        })

    missing_stems = dict.fromkeys(
        issue.image for issue in errors
        if issue.code == "MISSING_LABEL_FILE" and issue.image not in remove_stems
    )
    for stem in missing_stems:
        fixes.append({
            "image": stem, "line": None, "action": "needs_label",
            "before": "(không có file)", "after": "chuyển người gán",
        })

    line_ops = defaultdict(dict)
    for issue in errors:
        if issue.image in remove_stems or issue.line is None:
            continue
        if issue.code in drop_codes or issue.code == "BOX_OUT_OF_IMAGE":
            line_ops[issue.image].setdefault(issue.line, set()).add(issue.code)

    for stem, ops in line_ops.items():
        label_path = ds.label_path(stem)
        if not label_path.exists():
            continue
        original_lines = label_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        updated_lines = list(original_lines)
        changed = False

        for line_no in sorted(ops):
            index = line_no - 1
            if not 0 <= index < len(original_lines):
                continue
            before = original_lines[index].rstrip("\r\n")
            if ops[line_no] & drop_codes:
                updated_lines[index] = None
                fixes.append({
                    "image": stem, "line": line_no, "action": "drop_line",
                    "before": before, "after": "",
                })
                changed = True
                continue

            if "BOX_OUT_OF_IMAGE" not in ops[line_no]:
                continue
            try:
                cls, cx, cy, w, h = parse_yolo_line(before)
            except (ValueError, OverflowError):
                continue

            left, top = max(0.0, cx - w / 2), max(0.0, cy - h / 2)
            right, bottom = min(1.0, cx + w / 2), min(1.0, cy + h / 2)
            if right <= left or bottom <= top:
                updated_lines[index] = None
                fixes.append({
                    "image": stem, "line": line_no, "action": "drop_line",
                    "before": before, "after": "",
                })
                changed = True
                continue

            clipped = (
                cls,
                (left + right) / 2,
                (top + bottom) / 2,
                right - left,
                bottom - top,
            )
            after = f"{clipped[0]} " + " ".join(f"{value:.6f}" for value in clipped[1:])
            if after == before:
                continue
            newline = "\n" if original_lines[index].endswith(("\n", "\r")) else ""
            updated_lines[index] = after + newline
            fixes.append({
                "image": stem, "line": line_no, "action": "clip_box",
                "before": before, "after": after,
            })
            changed = True

        if changed:
            label_path.write_text(
                "".join(line for line in updated_lines if line is not None),
                encoding="utf-8",
            )

    return fixes
