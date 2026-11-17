def clean_cell(cell: str) -> str:
    return cell.strip().strip('"')


def to_float(cell: str) -> float:
    text = clean_cell(cell)
    if text in ("", "NA", "-"):
        return float("nan")
    return float(text)
