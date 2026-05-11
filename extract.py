#!/usr/bin/env python3
"""
Canvas IMSCC Course Extractor

Extracts content from Canvas LMS .imscc backup files into an organized,
browsable folder structure. Produces an index.html for easy navigation.

Zero dependencies — uses only the Python standard library.

Usage:
    python3 extract.py course_backup.imscc
    python3 extract.py course_backup.imscc -o output_folder
"""

import argparse
import html
import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

NS = {
    "ims": "http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1",
    "lom": "http://ltsc.ieee.org/xsd/imsccv1p1/LOM/resource",
    "lomimscc": "http://ltsc.ieee.org/xsd/imsccv1p1/LOM/manifest",
    "canvas": "http://canvas.instructure.com/xsd/cccv1p0",
    "dt": "http://www.imsglobal.org/xsd/imsccv1p1/imsdt_v1p1",
    "qti": "http://www.imsglobal.org/xsd/ims_qtiasiv1p2",
}


def slugify(text):
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text.strip())
    return text[:80].strip("-").lower()


def safe_filename(name, max_len=80):
    name = re.sub(r'[<>:"/\\|?*]', "", name)
    name = name.strip(". ")
    return name[:max_len] if name else "untitled"


def read_zip_text(zf, path):
    try:
        return zf.read(path).decode("utf-8")
    except (KeyError, UnicodeDecodeError):
        return None


def parse_xml(zf, path):
    text = read_zip_text(zf, path)
    if text is None:
        return None
    try:
        return ET.fromstring(text)
    except ET.ParseError:
        return None


def find_text(elem, xpath, ns=NS, default=""):
    if elem is None:
        return default
    node = elem.find(xpath, ns)
    return node.text.strip() if node is not None and node.text else default


def fix_html_links(content, file_base_path):
    content = re.sub(
        r'\$IMS-CC-FILEBASE\$/([^"?]*)',
        lambda m: f"{file_base_path}/{unquote(m.group(1))}",
        content,
    )
    content = re.sub(
        r'\$WIKI_REFERENCE\$/pages/([^"]*)',
        lambda m: f"../pages/{m.group(1)}.html",
        content,
    )
    content = re.sub(
        r'\$CANVAS_OBJECT_REFERENCE\$/(?:assignments|quizzes|modules)/([^"]*)',
        lambda m: f"#{m.group(1)}",
        content,
    )
    content = content.replace("$CANVAS_COURSE_REFERENCE$", "#")
    return content


# ---------------------------------------------------------------------------
# Parsers for each content type
# ---------------------------------------------------------------------------


def parse_course_settings(zf):
    root = parse_xml(zf, "course_settings/course_settings.xml")
    if root is None:
        return {}
    return {
        "title": find_text(root, "canvas:title"),
        "course_code": find_text(root, "canvas:course_code"),
        "start_at": find_text(root, "canvas:start_at"),
        "conclude_at": find_text(root, "canvas:conclude_at"),
        "license": find_text(root, "canvas:license"),
        "default_view": find_text(root, "canvas:default_view"),
    }


def parse_manifest(zf):
    root = parse_xml(zf, "imsmanifest.xml")
    if root is None:
        print("ERROR: No imsmanifest.xml found in archive.", file=sys.stderr)
        sys.exit(1)

    course_title = ""
    title_el = root.find(".//lomimscc:title/lomimscc:string", NS)
    if title_el is not None and title_el.text:
        course_title = title_el.text.strip()

    resources = {}
    for res in root.findall(".//ims:resource", NS):
        rid = res.get("identifier", "")
        rtype = res.get("type", "")
        href = res.get("href", "")
        files = [f.get("href", "") for f in res.findall("ims:file", NS)]
        deps = [d.get("identifierref", "") for d in res.findall("ims:dependency", NS)]
        resources[rid] = {
            "type": rtype,
            "href": href,
            "files": files,
            "dependencies": deps,
        }

    modules = []
    org = root.find(".//ims:organizations/ims:organization", NS)
    if org is not None:
        top = org.find("ims:item", NS)
        if top is not None:
            for mod_item in top.findall("ims:item", NS):
                mod = {
                    "identifier": mod_item.get("identifier", ""),
                    "title": "",
                    "items": [],
                }
                title_el = mod_item.find("ims:title", NS)
                if title_el is not None and title_el.text:
                    mod["title"] = title_el.text.strip()
                for child in mod_item.findall("ims:item", NS):
                    item = {
                        "identifier": child.get("identifier", ""),
                        "identifierref": child.get("identifierref", ""),
                        "title": "",
                        "children": [],
                    }
                    t = child.find("ims:title", NS)
                    if t is not None and t.text:
                        item["title"] = t.text.strip()
                    for subchild in child.findall("ims:item", NS):
                        sub = {
                            "identifier": subchild.get("identifier", ""),
                            "identifierref": subchild.get("identifierref", ""),
                            "title": "",
                        }
                        st = subchild.find("ims:title", NS)
                        if st is not None and st.text:
                            sub["title"] = st.text.strip()
                        item["children"].append(sub)
                    mod["items"].append(item)
                modules.append(mod)

    return course_title, resources, modules


def parse_module_meta(zf):
    root = parse_xml(zf, "course_settings/module_meta.xml")
    if root is None:
        return {}
    meta = {}
    for mod in root.findall("canvas:module", NS):
        mid = mod.get("identifier", "")
        items = []
        for item in mod.findall(".//canvas:item", NS):
            items.append(
                {
                    "identifier": find_text(item, "canvas:identifierref"),
                    "content_type": find_text(item, "canvas:content_type"),
                    "title": find_text(item, "canvas:title"),
                    "position": find_text(item, "canvas:position"),
                    "indent": find_text(item, "canvas:indent"),
                }
            )
        meta[mid] = {
            "title": find_text(mod, "canvas:title"),
            "position": find_text(mod, "canvas:position"),
            "unlock_at": find_text(mod, "canvas:unlock_at"),
            "items": items,
        }
    return meta


def parse_assignment_groups(zf):
    root = parse_xml(zf, "course_settings/assignment_groups.xml")
    if root is None:
        return {}
    groups = {}
    for ag in root.findall("canvas:assignmentGroup", NS):
        gid = ag.get("identifier", "")
        groups[gid] = {
            "title": find_text(ag, "canvas:title"),
            "position": find_text(ag, "canvas:position"),
            "group_weight": find_text(ag, "canvas:group_weight"),
        }
    return groups


def parse_rubrics(zf):
    root = parse_xml(zf, "course_settings/rubrics.xml")
    if root is None:
        return []
    rubrics = []
    for rub in root.findall("canvas:rubric", NS):
        criteria = []
        for crit in rub.findall(".//canvas:criterion", NS):
            ratings = []
            for rat in crit.findall(".//canvas:rating", NS):
                ratings.append(
                    {
                        "description": find_text(rat, "canvas:description"),
                        "long_description": find_text(rat, "canvas:long_description"),
                        "points": find_text(rat, "canvas:points"),
                    }
                )
            criteria.append(
                {
                    "description": find_text(crit, "canvas:description"),
                    "points": find_text(crit, "canvas:points"),
                    "ratings": ratings,
                }
            )
        rubrics.append(
            {
                "identifier": rub.get("identifier", ""),
                "title": find_text(rub, "canvas:title"),
                "points_possible": find_text(rub, "canvas:points_possible"),
                "criteria": criteria,
            }
        )
    return rubrics


def parse_assignment(zf, path):
    root = parse_xml(zf, path)
    if root is None:
        return None
    return {
        "identifier": root.get("identifier", ""),
        "title": find_text(root, "canvas:title"),
        "due_at": find_text(root, "canvas:due_at"),
        "points_possible": find_text(root, "canvas:points_possible"),
        "grading_type": find_text(root, "canvas:grading_type"),
        "submission_types": find_text(root, "canvas:submission_types"),
        "workflow_state": find_text(root, "canvas:workflow_state"),
        "group_ref": find_text(root, "canvas:assignment_group_identifierref"),
        "external_tool_url": find_text(root, "canvas:external_tool_url"),
    }


def parse_discussion(zf, path):
    root = parse_xml(zf, path)
    if root is None:
        return None
    return {
        "title": find_text(root, "dt:title"),
        "text": find_text(root, "dt:text"),
    }


def parse_qti_assessment(zf, path):
    text = read_zip_text(zf, path)
    if text is None:
        return None
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None

    tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    ns = ""
    if "}" in root.tag:
        ns = root.tag.split("}")[0] + "}"

    title = ""
    bank_title = ""
    for field in root.iter(f"{ns}qtimetadatafield"):
        label = field.find(f"{ns}fieldlabel")
        entry = field.find(f"{ns}fieldentry")
        if label is not None and entry is not None:
            if label.text == "bank_title":
                bank_title = entry.text or ""
            elif label.text == "title":
                title = entry.text or ""
    if not title:
        title = bank_title

    assessment_el = root.find(f"{ns}assessment")
    if assessment_el is not None:
        title = assessment_el.get("title", title)

    questions = []
    for item in root.iter(f"{ns}item"):
        q = {"title": item.get("title", ""), "type": "", "points": "", "text": ""}
        for field in item.findall(f".//{ns}qtimetadatafield"):
            label = field.find(f"{ns}fieldlabel")
            entry = field.find(f"{ns}fieldentry")
            if label is not None and entry is not None:
                if label.text == "question_type":
                    q["type"] = entry.text or ""
                elif label.text == "points_possible":
                    q["points"] = entry.text or ""

        for mattext in item.findall(f".//{ns}presentation/{ns}material/{ns}mattext"):
            q["text"] = mattext.text or ""

        choices = []
        correct_ids = set()
        for respcond in item.findall(f".//{ns}respcondition"):
            setvar = respcond.find(f"{ns}setvar")
            if setvar is not None and setvar.text and float(setvar.text) > 0:
                for ve in respcond.findall(f".//{ns}varequal"):
                    if ve.text:
                        correct_ids.add(ve.text.strip())

        for resp_label in item.findall(f".//{ns}response_label"):
            lid = resp_label.get("ident", "")
            choice_text = ""
            for mt in resp_label.findall(f".//{ns}mattext"):
                choice_text = mt.text or ""
            choices.append(
                {
                    "id": lid,
                    "text": choice_text,
                    "correct": lid in correct_ids,
                }
            )
        q["choices"] = choices
        if q["text"] or choices:
            questions.append(q)

    return {"title": title, "questions": questions}


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

PAGE_CSS = """\
:root {
    --brand: #8E0003;
    --accent: #e6aa3e;
    --bg: #fafafa;
    --card-bg: #ffffff;
    --text: #1a1a1a;
    --text-secondary: #555;
    --border: #e0e0e0;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
    max-width: 1100px;
    margin: 0 auto;
    padding: 20px;
}
a { color: var(--brand); text-decoration: none; }
a:hover { text-decoration: underline; }
h1 { color: var(--brand); margin-bottom: 8px; font-size: 1.8rem; }
h2 { color: var(--brand); margin: 24px 0 12px; font-size: 1.4rem; border-bottom: 2px solid var(--accent); padding-bottom: 6px; }
h3 { margin: 16px 0 8px; font-size: 1.1rem; }
.subtitle { color: var(--text-secondary); margin-bottom: 24px; }
.card {
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 12px;
}
.card h3 { margin-top: 0; }
.module-items { list-style: none; padding: 0; }
.module-items li { padding: 6px 0; border-bottom: 1px solid var(--border); display: flex; align-items: baseline; gap: 8px; }
.module-items li:last-child { border-bottom: none; }
.badge {
    font-size: 0.7rem;
    padding: 2px 8px;
    border-radius: 10px;
    background: var(--accent);
    color: #000;
    white-space: nowrap;
    font-weight: 600;
}
.badge-quiz { background: #d4edda; color: #155724; }
.badge-assignment { background: #cce5ff; color: #004085; }
.badge-discussion { background: #fff3cd; color: #856404; }
.badge-page { background: #e2e3e5; color: #383d41; }
.badge-header { background: transparent; color: var(--text-secondary); font-style: italic; font-weight: normal; }
.indent-1 { padding-left: 24px; }
.indent-2 { padding-left: 48px; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; }
th, td { padding: 8px 12px; border: 1px solid var(--border); text-align: left; }
th { background: var(--brand); color: #fff; }
tr:nth-child(even) { background: #f8f8f8; }
.question { margin-bottom: 20px; padding: 12px; border-left: 3px solid var(--brand); background: var(--card-bg); }
.question-text { margin-bottom: 8px; }
.choices { list-style: none; padding: 0; }
.choices li { padding: 4px 0 4px 20px; position: relative; }
.choices li::before { content: "○ "; position: absolute; left: 0; }
.choices li.correct { font-weight: bold; color: #155724; }
.choices li.correct::before { content: "● "; color: #155724; }
.points { color: var(--text-secondary); font-size: 0.85rem; }
.nav { background: var(--brand); padding: 12px 20px; border-radius: 8px; margin-bottom: 20px; }
.nav a { color: #fff; margin-right: 16px; font-weight: 500; }
.nav a:hover { color: var(--accent); text-decoration: none; }
.back-link { display: inline-block; margin-bottom: 16px; font-size: 0.9rem; }
.rubric-criterion { margin: 8px 0; }
.rating { margin-left: 16px; padding: 4px 0; }
.files-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 12px; }
.file-card { padding: 12px; border: 1px solid var(--border); border-radius: 6px; word-break: break-word; }
img { max-width: 100%; height: auto; }
details { margin: 8px 0; }
summary { cursor: pointer; padding: 4px 0; font-weight: 500; }
.content-body { padding: 12px; }
.content-body img { max-width: 100%; }
"""


def html_page(title, body, back_link=None, extra_head=""):
    back = ""
    if back_link:
        back = f'<a class="back-link" href="{back_link}">&larr; Back to Index</a>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)}</title>
<style>{PAGE_CSS}</style>
{extra_head}
</head>
<body>
{back}
{body}
</body>
</html>
"""


def badge_for_type(content_type):
    t = content_type.lower()
    if "quiz" in t or "assessment" in t:
        return '<span class="badge badge-quiz">Quiz</span>'
    if "assignment" in t:
        return '<span class="badge badge-assignment">Assignment</span>'
    if "discussion" in t:
        return '<span class="badge badge-discussion">Discussion</span>'
    if "wiki" in t or "page" in t:
        return '<span class="badge badge-page">Page</span>'
    if "subheader" in t or "header" in t:
        return '<span class="badge badge-header">Section</span>'
    if "external" in t or "lti" in t:
        return '<span class="badge">External Tool</span>'
    return ""


def render_question_html(q, idx):
    parts = [f'<div class="question">']
    parts.append(f'<strong>Q{idx}.</strong> ')
    if q.get("points"):
        parts.append(f'<span class="points">({q["points"]} pts)</span> ')
    qtype = q.get("type", "").replace("_", " ").title()
    if qtype:
        parts.append(f'<span class="points">[{qtype}]</span>')
    parts.append(f'<div class="question-text">{q.get("text", "")}</div>')
    if q.get("choices"):
        parts.append('<ul class="choices">')
        for c in q["choices"]:
            cls = ' class="correct"' if c.get("correct") else ""
            parts.append(f"<li{cls}>{c['text']}</li>")
        parts.append("</ul>")
    parts.append("</div>")
    return "\n".join(parts)


def render_rubric_html(rubric):
    parts = [f'<div class="card">']
    parts.append(
        f'<h3>{html.escape(rubric["title"])} '
        f'<span class="points">({rubric["points_possible"]} pts)</span></h3>'
    )
    for crit in rubric.get("criteria", []):
        parts.append(
            f'<div class="rubric-criterion"><strong>'
            f'{html.escape(crit["description"])}</strong> '
            f'({crit["points"]} pts)</div>'
        )
        for rat in crit.get("ratings", []):
            parts.append(
                f'<div class="rating">{html.escape(rat["description"])} '
                f'({rat["points"]} pts)'
            )
            if rat.get("long_description"):
                parts.append(f" &mdash; {html.escape(rat['long_description'])}")
            parts.append("</div>")
    parts.append("</div>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------


def extract(imscc_path, output_dir):
    imscc_path = Path(imscc_path)
    output_dir = Path(output_dir)

    if not imscc_path.exists():
        print(f"ERROR: File not found: {imscc_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Opening {imscc_path.name} ...")
    zf = zipfile.ZipFile(imscc_path, "r")

    course_title, resources, manifest_modules = parse_manifest(zf)
    course_settings = parse_course_settings(zf)
    if course_settings.get("title"):
        course_title = course_settings["title"]
    module_meta = parse_module_meta(zf)
    assignment_groups = parse_assignment_groups(zf)
    rubrics = parse_rubrics(zf)

    print(f"Course: {course_title}")
    print(f"Resources: {len(resources)}")
    print(f"Modules: {len(manifest_modules)}")

    dirs = {
        "pages": output_dir / "pages",
        "assessments": output_dir / "assessments",
        "discussions": output_dir / "discussions",
        "files": output_dir / "files",
        "assignments": output_dir / "assignments",
    }
    for d in dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    file_base_path = "../files"
    page_map = {}  # identifier -> filename
    assessment_map = {}  # identifier -> filename
    discussion_map = {}  # identifier -> filename
    assignment_map = {}  # identifier -> data dict

    # --- Extract wiki pages ---
    wiki_files = [n for n in zf.namelist() if n.startswith("wiki_content/") and n.endswith(".html")]
    print(f"Extracting {len(wiki_files)} pages ...")
    for wf in wiki_files:
        content = read_zip_text(zf, wf)
        if content is None:
            continue
        content = fix_html_links(content, file_base_path)

        stem = Path(wf).stem
        title_match = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE)
        page_title = title_match.group(1) if title_match else stem

        identifier = ""
        id_match = re.search(r'name="identifier"\s+content="([^"]*)"', content)
        if id_match:
            identifier = id_match.group(1)

        body_match = re.search(r"<body>(.*)</body>", content, re.DOTALL | re.IGNORECASE)
        body = body_match.group(1) if body_match else content

        page_html = html_page(
            page_title,
            f"<h1>{html.escape(page_title)}</h1>\n<div class='content-body'>{body}</div>",
            back_link="../index.html",
        )

        fname = f"{slugify(stem)}.html"
        (dirs["pages"] / fname).write_text(page_html, encoding="utf-8")
        if identifier:
            page_map[identifier] = f"pages/{fname}"
        for rid, res in resources.items():
            if res.get("href") == wf:
                page_map[rid] = f"pages/{fname}"

    # --- Extract discussions ---
    discussion_xmls = {
        rid: res
        for rid, res in resources.items()
        if res["type"] == "imsdt_xmlv1p1"
    }
    print(f"Extracting {len(discussion_xmls)} discussions ...")
    for rid, res in discussion_xmls.items():
        href = res.get("href", "")
        if not href:
            href = next((f for f in res.get("files", []) if f.endswith(".xml")), "")
        if not href:
            continue
        disc = parse_discussion(zf, href)
        if disc is None:
            continue
        title = disc["title"] or rid
        body = fix_html_links(disc.get("text", ""), file_base_path)
        disc_html = html_page(
            title,
            f"<h1>{html.escape(title)}</h1>\n<div class='content-body'>{body}</div>",
            back_link="../index.html",
        )
        fname = f"{slugify(title)}.html"
        (dirs["discussions"] / fname).write_text(disc_html, encoding="utf-8")
        discussion_map[rid] = f"discussions/{fname}"

    # --- Extract assessments (QTI) ---
    # 1. Parse all QTI files and build question bank map (objectbank ident -> data)
    qti_files = [n for n in zf.namelist() if n.endswith(".xml.qti")]
    print(f"Extracting {len(qti_files)} question banks ...")
    qbank_by_ident = {}  # objectbank ident -> {title, questions, fname}
    qbank_by_file = {}  # file stem -> same
    for qf in qti_files:
        assessment = parse_qti_assessment(zf, qf)
        if assessment is None:
            continue
        title = assessment["title"] or Path(qf).stem
        qid = Path(qf).stem.replace(".xml", "")
        questions = assessment.get("questions", [])

        if not questions:
            qbank_by_file[qid] = {"title": title, "fname": "", "count": 0, "ident": qid}
            continue

        fname = f"{slugify(title)}-{qid[:8]}.html"
        body_parts = [f"<h1>{html.escape(title)}</h1>"]
        body_parts.append(
            f'<p class="subtitle">Question Bank &mdash; '
            f'{len(questions)} question(s)</p>'
        )
        for i, q in enumerate(questions, 1):
            body_parts.append(render_question_html(q, i))
        assess_html = html_page(title, "\n".join(body_parts), back_link="../index.html")
        (dirs["assessments"] / fname).write_text(assess_html, encoding="utf-8")

        bank_data = {"title": title, "fname": fname, "count": len(questions), "ident": qid}
        qbank_by_file[qid] = bank_data

        # Also map by objectbank ident (may differ from filename)
        text = read_zip_text(zf, qf)
        if text:
            for m in re.finditer(r'<objectbank\s+ident="([^"]*)"', text):
                qbank_by_ident[m.group(1)] = bank_data

    # 2. Parse quiz sourcebank_ref to find which banks each quiz uses
    def parse_quiz_bank_refs(zf, qti_path):
        text = read_zip_text(zf, qti_path)
        if not text:
            return []
        refs = []
        for m in re.finditer(
            r'<sourcebank_ref>(.*?)</sourcebank_ref>.*?'
            r'<selection_number>(.*?)</selection_number>.*?'
            r'<points_per_item>(.*?)</points_per_item>',
            text, re.DOTALL,
        ):
            refs.append({
                "bank_ref": m.group(1).strip(),
                "pick_count": m.group(2).strip(),
                "points_each": m.group(3).strip(),
            })
        return refs

    # 3. Build quiz pages
    quiz_resources = {
        rid: res for rid, res in resources.items()
        if res["type"] == "imsqti_xmlv1p2/imscc_xmlv1p1/assessment"
    }
    print(f"Processing {len(quiz_resources)} quizzes ...")
    for rid, res in quiz_resources.items():
        meta_path = f"{rid}/assessment_meta.xml"
        non_cc_path = f"non_cc_assessments/{rid}.xml.qti"
        meta = parse_xml(zf, meta_path)

        quiz_title = rid
        quiz_info = {}
        if meta is not None:
            quiz_title = find_text(meta, "canvas:title") or rid
            quiz_info = {
                "points_possible": find_text(meta, "canvas:points_possible"),
                "due_at": find_text(meta, "canvas:due_at"),
                "lock_at": find_text(meta, "canvas:lock_at"),
                "allowed_attempts": find_text(meta, "canvas:allowed_attempts"),
                "quiz_type": find_text(meta, "canvas:quiz_type"),
                "scoring_policy": find_text(meta, "canvas:scoring_policy"),
                "time_limit": find_text(meta, "canvas:time_limit"),
                "description": find_text(meta, "canvas:description"),
            }

        body_parts = [f"<h1>{html.escape(quiz_title)}</h1>"]

        info_parts = []
        if quiz_info.get("points_possible"):
            info_parts.append(f"<strong>Points:</strong> {quiz_info['points_possible']}")
        if quiz_info.get("due_at"):
            info_parts.append(f"<strong>Due:</strong> {quiz_info['due_at'][:16]}")
        if quiz_info.get("lock_at"):
            info_parts.append(f"<strong>Locks:</strong> {quiz_info['lock_at'][:16]}")
        if quiz_info.get("allowed_attempts"):
            att = "Unlimited" if quiz_info["allowed_attempts"] == "-1" else quiz_info["allowed_attempts"]
            info_parts.append(f"<strong>Attempts:</strong> {att}")
        if quiz_info.get("time_limit"):
            info_parts.append(f"<strong>Time Limit:</strong> {quiz_info['time_limit']} min")
        if quiz_info.get("scoring_policy"):
            info_parts.append(f"<strong>Scoring:</strong> {quiz_info['scoring_policy'].replace('_', ' ')}")
        if info_parts:
            body_parts.append(f'<p class="subtitle">{" &nbsp;|&nbsp; ".join(info_parts)}</p>')

        if quiz_info.get("description"):
            body_parts.append(f'<div class="card content-body">{fix_html_links(quiz_info["description"], file_base_path)}</div>')

        # Parse sourcebank_ref from the quiz QTI
        bank_refs = parse_quiz_bank_refs(zf, non_cc_path)
        if not bank_refs:
            bank_refs = parse_quiz_bank_refs(zf, f"{rid}/assessment_qti.xml")

        if bank_refs:
            body_parts.append('<h2>Question Groups</h2>')
            total_q = 0
            for ref in bank_refs:
                bank = qbank_by_ident.get(ref["bank_ref"], qbank_by_file.get(ref["bank_ref"]))
                if bank and bank.get("fname"):
                    body_parts.append(
                        f'<div class="card">'
                        f'<a href="{bank["fname"]}">{html.escape(bank["title"])}</a>'
                        f' &mdash; pick {ref["pick_count"]} &times; {ref["points_each"]} pts'
                        f' (from {bank["count"]} questions in bank)</div>'
                    )
                    total_q += bank["count"]
                else:
                    body_parts.append(
                        f'<div class="card">Question group: pick {ref["pick_count"]}'
                        f' &times; {ref["points_each"]} pts'
                        f' (bank ref: {ref["bank_ref"][:12]}...)</div>'
                    )
            if total_q:
                body_parts.append(f'<p class="points">Total questions across all banks: {total_q}</p>')
        else:
            # Try inline questions from the assessment QTI
            inline = parse_qti_assessment(zf, f"{rid}/assessment_qti.xml")
            if inline and inline.get("questions"):
                body_parts.append(f'<h2>Questions ({len(inline["questions"])})</h2>')
                for i, q in enumerate(inline["questions"], 1):
                    body_parts.append(render_question_html(q, i))

        fname = f"{slugify(quiz_title)}-{rid[:8]}.html"
        quiz_html = html_page(quiz_title, "\n".join(body_parts), back_link="../index.html")
        (dirs["assessments"] / fname).write_text(quiz_html, encoding="utf-8")
        assessment_map[rid] = f"assessments/{fname}"

    # --- Extract assignment metadata ---
    for name in zf.namelist():
        if name.endswith("/assignment_settings.xml"):
            asgn = parse_assignment(zf, name)
            if asgn:
                assignment_map[asgn["identifier"]] = asgn
                group_title = assignment_groups.get(
                    asgn.get("group_ref", ""), {}
                ).get("title", "")
                asgn["group_title"] = group_title

    # --- Extract files (images, PDFs, media) ---
    file_prefixes = ("web_resources/", "Media/", "Files/", "images/")
    file_entries = [
        n
        for n in zf.namelist()
        if any(n.startswith(p) for p in file_prefixes) and not n.endswith("/")
    ]
    print(f"Extracting {len(file_entries)} files ...")
    for fe in file_entries:
        rel_parts = fe.split("/", 1)
        if len(rel_parts) < 2:
            continue
        rel_path = rel_parts[1] if rel_parts[0] == "web_resources" else fe
        out_path = dirs["files"] / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            out_path.write_bytes(zf.read(fe))
        except KeyError:
            pass

    # --- Build index.html ---
    print("Building index.html ...")
    body_parts = []
    body_parts.append(f"<h1>{html.escape(course_title)}</h1>")

    info_items = []
    if course_settings.get("course_code"):
        info_items.append(f"<strong>Course Code:</strong> {html.escape(course_settings['course_code'])}")
    if course_settings.get("start_at"):
        info_items.append(f"<strong>Start:</strong> {html.escape(course_settings['start_at'][:10])}")
    if course_settings.get("conclude_at"):
        info_items.append(f"<strong>End:</strong> {html.escape(course_settings['conclude_at'][:10])}")
    if info_items:
        body_parts.append(f'<p class="subtitle">{" &nbsp;|&nbsp; ".join(info_items)}</p>')

    body_parts.append('<div class="nav">')
    body_parts.append('<a href="#modules">Modules</a>')
    body_parts.append('<a href="#assessments">Assessments</a>')
    body_parts.append('<a href="#rubrics">Rubrics</a>')
    body_parts.append('<a href="#files">Files</a>')
    body_parts.append("</div>")

    # Syllabus
    syllabus = read_zip_text(zf, "course_settings/syllabus.html")
    if syllabus and syllabus.strip() and len(syllabus.strip()) > 50:
        body_parts.append('<h2>Syllabus</h2>')
        body_parts.append(f'<div class="card content-body">{syllabus}</div>')

    # Modules section
    body_parts.append('<h2 id="modules">Modules</h2>')

    sorted_modules = manifest_modules
    if module_meta:
        pos_map = {}
        for mid, mm in module_meta.items():
            try:
                pos_map[mid] = int(mm.get("position", 999))
            except ValueError:
                pos_map[mid] = 999
        sorted_modules = sorted(
            manifest_modules, key=lambda m: pos_map.get(m["identifier"], 999)
        )

    for mod_idx, mod in enumerate(sorted_modules, 1):
        mod_id = mod["identifier"]
        meta = module_meta.get(mod_id, {})
        mod_title = meta.get("title") or mod.get("title") or f"Module {mod_idx}"

        body_parts.append(f'<div class="card">')
        body_parts.append(f"<h3>{html.escape(mod_title)}</h3>")

        if meta.get("unlock_at"):
            body_parts.append(
                f'<p class="points">Unlocks: {html.escape(meta["unlock_at"][:10])}</p>'
            )

        meta_items = meta.get("items", [])
        manifest_items = mod.get("items", [])
        items_to_render = meta_items if meta_items else []

        if not items_to_render and manifest_items:
            items_to_render = []
            for mi in manifest_items:
                ct = "WikiPage"
                ref = mi.get("identifierref", "")
                if ref in resources:
                    rtype = resources[ref]["type"]
                    if "imsdt" in rtype:
                        ct = "DiscussionTopic"
                    elif "assessment" in rtype:
                        ct = "Quizzes::Quiz"
                    elif "assignment" in rtype or ref in assignment_map:
                        ct = "Assignment"
                    elif "lti" in rtype:
                        ct = "ContextExternalTool"
                elif not ref:
                    ct = "ContextModuleSubHeader"
                items_to_render.append(
                    {
                        "identifier": ref,
                        "content_type": ct,
                        "title": mi.get("title", ""),
                        "indent": "0",
                    }
                )

        if items_to_render:
            body_parts.append('<ul class="module-items">')
            for item in items_to_render:
                iref = item.get("identifier", "")
                itype = item.get("content_type", "")
                ititle = item.get("title", iref)
                indent = item.get("indent", "0")

                indent_cls = ""
                try:
                    ind = int(indent)
                    if ind >= 1:
                        indent_cls = f" indent-{min(ind, 2)}"
                except ValueError:
                    pass

                link = ""
                if iref in page_map:
                    link = page_map[iref]
                elif iref in discussion_map:
                    link = discussion_map[iref]
                elif iref in assessment_map:
                    link = assessment_map[iref]

                badge = badge_for_type(itype)

                asgn_info = ""
                if iref in assignment_map and isinstance(assignment_map[iref], dict):
                    a = assignment_map[iref]
                    parts = []
                    if a.get("points_possible"):
                        parts.append(f'{a["points_possible"]} pts')
                    if a.get("due_at"):
                        parts.append(f'due {a["due_at"][:10]}')
                    if a.get("group_title"):
                        parts.append(a["group_title"])
                    if parts:
                        asgn_info = f' <span class="points">({", ".join(parts)})</span>'

                title_html = html.escape(ititle)
                if link:
                    title_html = f'<a href="{link}">{title_html}</a>'

                body_parts.append(
                    f'<li class="{indent_cls.strip()}">{badge} {title_html}{asgn_info}</li>'
                )
            body_parts.append("</ul>")

        body_parts.append("</div>")

    # Assignment Groups summary
    if assignment_groups:
        body_parts.append("<h2>Grading Breakdown</h2>")
        body_parts.append('<table><tr><th>Category</th><th>Weight</th></tr>')
        for gid, grp in sorted(
            assignment_groups.items(), key=lambda x: int(x[1].get("position", 999))
        ):
            body_parts.append(
                f'<tr><td>{html.escape(grp["title"])}</td>'
                f'<td>{grp.get("group_weight", "")}%</td></tr>'
            )
        body_parts.append("</table>")

    # Assessments listing
    body_parts.append('<h2 id="assessments">Assessments</h2>')
    if assessment_map:
        body_parts.append('<div class="files-grid">')
        seen = set()
        for aid, apath in assessment_map.items():
            if apath in seen:
                continue
            seen.add(apath)
            name = Path(apath).stem.replace("-", " ").title()
            body_parts.append(
                f'<div class="file-card"><a href="{apath}">{html.escape(name)}</a></div>'
            )
        body_parts.append("</div>")
    else:
        body_parts.append("<p>No assessments found.</p>")

    # Rubrics
    if rubrics:
        body_parts.append('<h2 id="rubrics">Rubrics</h2>')
        for rub in rubrics:
            body_parts.append(render_rubric_html(rub))

    # Files listing
    body_parts.append('<h2 id="files">Files</h2>')
    extracted_files = sorted(dirs["files"].rglob("*"))
    extracted_files = [f for f in extracted_files if f.is_file()]
    if extracted_files:
        body_parts.append(f"<p>{len(extracted_files)} files extracted</p>")
        by_type = {}
        for ef in extracted_files:
            ext = ef.suffix.lower() or "(no extension)"
            by_type.setdefault(ext, []).append(ef)
        for ext in sorted(by_type.keys()):
            files_list = by_type[ext]
            body_parts.append(f"<details><summary>{ext} ({len(files_list)} files)</summary>")
            body_parts.append('<div class="files-grid">')
            for ef in files_list:
                rel = ef.relative_to(output_dir)
                body_parts.append(
                    f'<div class="file-card"><a href="{rel}">{html.escape(ef.name)}</a></div>'
                )
            body_parts.append("</div></details>")
    else:
        body_parts.append("<p>No files extracted.</p>")

    # Footer
    body_parts.append(
        '<hr style="margin-top:40px">'
        '<p class="points">Extracted by Canvas IMSCC Extractor &mdash; '
        "helping teachers recover their course content.</p>"
    )

    index_html = html_page(course_title, "\n".join(body_parts))
    (output_dir / "index.html").write_text(index_html, encoding="utf-8")

    zf.close()
    print(f"\nDone! Output written to: {output_dir}")
    print(f"Open {output_dir / 'index.html'} in your browser to browse the course.")


def main():
    parser = argparse.ArgumentParser(
        description="Extract content from Canvas LMS .imscc backup files.",
        epilog="Example: python3 extract.py my_course.imscc -o my_course_output",
    )
    parser.add_argument("imscc_file", help="Path to the .imscc file")
    parser.add_argument(
        "-o",
        "--output",
        help="Output directory (default: derived from filename)",
    )
    args = parser.parse_args()

    imscc_path = Path(args.imscc_file)
    if args.output:
        output_dir = Path(args.output)
    else:
        output_dir = Path(imscc_path.stem.replace(" ", "_") + "_extracted")

    extract(imscc_path, output_dir)


if __name__ == "__main__":
    main()
