#!/usr/bin/env python3
from __future__ import annotations
import json, re, sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

TEMPLATE_LIST_PATH = Path("lists/template_list.json")
OUTPUT_DIR = Path("generated_data/template_schema")

# ---------- fetch helpers ----------
def to_raw_github(url: str) -> str:
    if "raw.githubusercontent.com" in url:
        return url
    if "github.com" in url and "/blob/" in url:
        return url.replace("https://github.com/", "https://raw.githubusercontent.com/").replace("/blob/", "/")
    return url

def fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "flexera-ptl-scraper/2.7"})
    with urlopen(req) as r:
        enc = r.headers.get_content_charset() or "utf-8"
        return r.read().decode(enc, errors="replace")

def basename_from_url(url: str) -> str:
    name = url.split("/")[-1]
    return name[:-3] if name.endswith(".pt") else name

# ---------- block scanning ----------
def scan_block(text: str, start_after_do: int) -> tuple[int, int]:
    i = start_after_do
    depth = 1
    in_s = None
    esc = False
    in_hd = False
    hd_term = None
    def is_word_at(t, idx, word):
        return t.startswith(word, idx) and (idx==0 or not t[idx-1].isalnum()) and (idx+len(word)==len(t) or not t[idx+len(word)].isalnum())
    while i < len(text):
        c = text[i]
        if in_hd:
            if hd_term and is_word_at(text, i, hd_term):
                i += len(hd_term); in_hd = False; hd_term = None; continue
            i += 1; continue
        if in_s:
            if not esc and c == in_s: in_s = None
            esc = (not esc and c == "\\"); i += 1; continue
        if c in ("'", '"'):
            in_s = c; i += 1; continue
        if text.startswith("<<-", i) or text.startswith("<<", i):
            m = re.match(r"<<-?'?([A-Za-z_][A-Za-z0-9_]*)'?", text[i:])
            if m: hd_term = m.group(1); in_hd = True; i += m.end(); continue
        if is_word_at(text, i, "do"): depth += 1; i += 2; continue
        if is_word_at(text, i, "end"):
            depth -= 1; i += 3
            if depth == 0: return (start_after_do - 2, i)
            continue
        i += 1
    return (start_after_do - 2, len(text))

def find_blocks(text: str, head_regex: re.Pattern) -> list[tuple[int,int]]:
    out = []
    for m in head_regex.finditer(text):
        s = m.end()
        do_match = re.search(r"\bdo\b", text[s:])
        if not do_match: continue
        do_after = s + do_match.end()
        block_start, block_end = scan_block(text, do_after)
        out.append((m.start(), block_end))
    return out

# ---------- info()/metadata helpers ----------
def _info_field(text: str, key: str) -> str | None:
    m_info = re.search(r'info\s*\(([^)]*)\)', text, flags=re.DOTALL)
    if not m_info:
        return None
    body = m_info.group(1)
    pattern = fr'\b{re.escape(key)}\s*:\s*([\'"])(?P<v>.+?)\1'
    m = re.search(pattern, body)
    return m.group("v") if m else None

def extract_top_level_string(key: str, text: str) -> str | None:
    # heredoc first
    m = re.search(fr'^\s*{re.escape(key)}\s+<<-?\'?([A-Za-z_][A-Za-z0-9_]*)\'?', text, flags=re.M)
    if m:
        term = m.group(1)
        m2 = re.search(fr'{re.escape(term)}\s*$', text, flags=re.M)
        if m2:
            start = m.end()
            end = m2.start()
            return text[start:end].strip()
    # quoted
    m = re.search(fr'^\s*{re.escape(key)}\s+([\'"])(?P<v>.+?)\1\s*$', text, flags=re.M)
    return m.group("v") if m else None

def parse_metadata_and_info(text: str) -> dict:
    name = extract_top_level_string("name", text)
    version = _info_field(text, "version") or extract_top_level_string("version", text)
    provider = _info_field(text, "provider")
    service = _info_field(text, "service")
    policy_set = _info_field(text, "policy_set")
    recommendation_type = _info_field(text, "recommendation_type")
    short_description = extract_top_level_string("short_description", text)
    return {
        "name": name,
        "version": version,
        "cloud": provider,
        "service": service,
        "policy_set": policy_set,
        "recommendation_type": recommendation_type,
        "short_description": short_description,
    }

# ---------- extractors ----------
def extract_summary(block: str) -> str | None:
    m = re.search(r"summary_template\s+<<-?'(\w+)'\s*(.*?)\1", block, flags=re.DOTALL)
    if m: return m.group(2).strip()
    m = re.search(r'summary_template\s+([\'"])(.*?)\1', block, flags=re.DOTALL)
    return m.group(2).strip() if m else None

def extract_detail(block: str) -> str | None:
    m = re.search(r"detail_template\s+<<-?'(\w+)'\s*(.*?)\1", block, flags=re.DOTALL)
    if m: return m.group(2).strip()
    m = re.search(r'detail_template\s+([\'"])(.*?)\1', block, flags=re.DOTALL)
    return m.group(2).strip() if m else None

def extract_export_fields(export_block: str) -> list[dict]:
    fields = []
    for fm in re.finditer(r'field\s+([\'"])(?P<name>.+?)\1\s+do', export_block):
        start_after_do = fm.end()
        _, fend = scan_block(export_block, start_after_do)
        fcontent = export_block[start_after_do:fend-3]
        name = fm.group("name")
        label = None
        path = None
        ml = re.search(r'\blabel\s+([\'"])(?P<v>.+?)\1', fcontent)
        if ml: label = ml.group("v")
        mp = re.search(r'\bpath\s+([\'"])(?P<v>.+?)\1', fcontent)
        if mp: path = mp.group("v")
        entry = {"name": name}
        if label: entry["label"] = label
        if path: entry["path"] = path
        fields.append(entry)
    for fm in re.finditer(r'field\s+([\'"])(?P<name>.+?)\1\s*,\s*(?P<kw>[^;]*?)(?:\bend\b|\n|$)', export_block):
        name = fm.group("name"); kw = fm.group("kw")
        label = re.search(r'label\s*:\s*([\'"])(?P<v>.+?)\1', kw)
        path  = re.search(r'path\s*:\s*([\'"])(?P<v>.+?)\1',  kw)
        entry = {"name": name}
        if label: entry["label"] = label.group("v")
        if path:  entry["path"]  = path.group("v")
        if not any(x["name"] == name for x in fields):
            fields.append(entry)
    return fields

# ---------- policy_name replacement ----------
def replace_policy_name_refs(text: str, template_name: str) -> str:
    if not text or not template_name:
        return text
    with_block = re.compile(r"{{-?\s*with\b[^}]*}}([\s\S]*?){{-?\s*end\s*-?}}", re.IGNORECASE)
    policy_ref  = re.compile(r"{{[^}]*\.(?:summary_)?policy_name[^}]*}}", re.IGNORECASE)
    prev = None; out = text
    while prev != out:
        prev = out
        def repl(m):
            inner = m.group(1)
            return template_name if policy_ref.search(inner) else m.group(0)
        out = with_block.sub(repl, out)
    out = re.sub(r"{{-?\s*\.(?:summary_)?policy_name\s*-?}}", template_name, out, flags=re.IGNORECASE)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"\s+(:)", r"\1", out)
    return out

# ---------- incident parsing ----------
def parse_incidents(text: str, template_name: str) -> list[dict]:
    incidents = []
    vblocks = find_blocks(text, re.compile(r'\bvalidate(?:_each)?\b[\s\S]*?'))
    for v_start, v_end in vblocks:
        vblock = text[v_start:v_end]
        summary = extract_summary(vblock)
        detail  = extract_detail(vblock)
        if summary: summary = replace_policy_name_refs(summary, template_name)
        if detail:  detail  = replace_policy_name_refs(detail,  template_name)
        exports = []
        for e_start, e_end in find_blocks(vblock, re.compile(r'\bexport\b')):
            eblock = vblock[e_start:e_end]
            exports.extend(extract_export_fields(eblock))
        inc = {}
        if summary is not None: inc["summary_template"] = summary
        if detail  is not None: inc["detail_template"]  = detail
        if exports:             inc["export"]           = exports
        if inc:                 incidents.append(inc)
    return incidents

# ---------- main ----------
def main():
    list_path = Path(sys.argv[1]) if len(sys.argv) > 1 else TEMPLATE_LIST_PATH
    out_dir   = Path(sys.argv[2]) if len(sys.argv) > 2 else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(list_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        if not isinstance(data, list):
            raise SystemExit("lists/template_list.json must be a JSON array")

        # Handle both old format (list of strings) and new format (list of objects with "url" key)
        urls = []
        for item in data:
            if isinstance(item, str):
                urls.append(item)
            elif isinstance(item, dict) and "url" in item:
                urls.append(item["url"])
            else:
                print(f"[WARN] Skipping invalid item: {item}", file=sys.stderr)

    for url in urls:
        raw  = to_raw_github(url)
        base = basename_from_url(raw)  # e.g., aws_rightsize_ec2_instances
        try:
            pt = fetch_text(raw)
        except (URLError, HTTPError) as e:
            print(f"[WARN] fetch failed: {raw} ({e})", file=sys.stderr)
            continue

        meta = parse_metadata_and_info(pt)
        incidents = parse_incidents(pt, meta.get("name") or "")

        # NEW: add a "path" to each incident pointing at the fake table file
        for i, inc in enumerate(incidents, start=1):
            inc["path"] = f"generated_data/fake_incident_tables/{base}_{i}.json"

        out = {
            "name": meta.get("name"),
            "version": meta.get("version"),
            "cloud": meta.get("cloud"),
            "service": meta.get("service"),
            "policy_set": meta.get("policy_set"),
            "recommendation_type": meta.get("recommendation_type"),
            "short_description": meta.get("short_description"),
            "url": to_raw_github(url),
            "filename": Path(url).stem,
            "incident": incidents,
        }
        out = {k: v for k, v in out.items() if v is not None}

        outfile = out_dir / f"{base}.json"
        with open(outfile, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        print(f"[OK] wrote {outfile}", file=sys.stderr)

if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    main()
