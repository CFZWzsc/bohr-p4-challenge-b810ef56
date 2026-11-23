#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evidence-driven claim auditing and writing skill.

Splits a draft into checkable claims, binds each claim to the cited references,
grades evidence strength from study design and sample size, and flags
overclaims, unsupported assertions and topical mismatches.

Standard library only. Deterministic, no network, no random.
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, OrderedDict

DEFAULT_CASE = "/input/case.json"
DEFAULT_OUT = "/app/output/result.json"
DEFAULT_WORK = "/app/work"

DESIGN_GRADES = [
    ("meta_analysis", 5, r"meta[- ]analyse?s?|systematic review|pooled analysis|荟萃分析|系统综述"),
    ("rct", 4, r"randomi[sz]ed controlled|randomi[sz]ed trial|\bRCT\b|随机对照"),
    ("cohort", 3, r"prospective cohort|retrospective cohort|cohort study|队列研究"),
    ("case_control", 3, r"case[- ]control|病例对照"),
    ("cross_sectional", 2, r"cross[- ]sectional|survey study|横断面|调查研究"),
    ("case_report", 1, r"case report|case series|病例报告|个案"),
    ("review", 2, r"\breview\b|overview|综述"),
    ("preprint", 1, r"preprint|bioRxiv|medRxiv|arXiv"),
    ("in_vitro", 1, r"in vitro|cell line|animal model|mice|rats|体外|动物实验"),
]

STRONG_VERBS = r"(proves?|proven|demonstrates?|establishes?|confirms?|shows? that|clearly|undoubtedly|always|never|causes?|leads? to|results? in|cures?|eliminates?|证明|证实|表明|导致|必然|完全|消除)"
HEDGES = r"(may|might|could|suggest|suggests|indicate|indicates|appear|appears|is associated with|are associated with|potential|possibly|likely|unlikely|可能|提示|相关|倾向于|尚需)"
CAUSAL = r"(causes?|caused by|leads? to|results? in|due to|because of|导致|引起|造成)"
CORRELATION = r"(associated with|correlat|linked to|相关|关联)"

TEXT_KEYS = ("manuscript", "draft", "document", "text", "content", "body",
             "claims", "claim_list", "paragraphs")
REF_KEYS = ("references", "evidence", "evidence_table", "sources", "library",
            "reference_list", "bibliography")


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read()


def clamp(text, limit=300):
    text = str(text).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + " …"


def norm_key(text):
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def find_task_text(case_path):
    base = os.path.dirname(os.path.abspath(case_path))
    for path in (os.path.join(base, "task.md"), os.path.join(base, "..", "task.md"),
                 "/input/task.md"):
        if os.path.isfile(path):
            try:
                return read_text(path)
            except OSError:
                continue
    return ""


def contract_fields(spec):
    if isinstance(spec, list):
        return [str(item) if isinstance(item, str) else str(item.get("name") or item.get("field"))
                for item in spec
                if isinstance(item, str) or (isinstance(item, dict)
                                             and (item.get("name") or item.get("field")))]
    if isinstance(spec, dict):
        if isinstance(spec.get("properties"), dict):
            return [str(name) for name in spec["properties"]]
        if isinstance(spec.get("fields"), (dict, list)):
            return contract_fields(spec["fields"])
        reserved = {"$schema", "title", "description", "type", "required", "definitions", "$defs"}
        return [str(name) for name in spec if str(name).lower() not in reserved]
    return []


def finalize(case, payload, contract):
    out = OrderedDict()
    out["case_id"] = case.get("case_id") or case.get("id")
    notes = [] if contract is not None else ["case.json 未声明 output_contract；已按本题通用字段输出。"]
    aliases = {"claims": {"claims", "claimtable", "claimlist", "claimmap"},
               "evidence_table": {"evidencetable", "evidence", "evidencemap"},
               "draft": {"draft", "manuscript", "text", "deliverable", "revisedtext"},
               "uncertainty": {"uncertainty", "uncertainties", "warnings"}}
    for name in contract_fields(contract):
        if norm_key(name) == "caseid":
            continue
        if name in payload:
            out[name] = payload[name]
            continue
        matched = next((payload[key] for key in payload if norm_key(key) == norm_key(name)), None)
        if matched is None:
            for canonical, names in aliases.items():
                if canonical in payload and norm_key(name) in names:
                    matched = payload[canonical]
                    break
        out[name] = matched
        if matched is None:
            notes.append("字段 %s 不在本 Skill 的能力范围内，按契约保留为 null。" % name)
    defaults = {"status": "partial", "result": {}, "evidence": [], "uncertainty": [],
                "errors": [], "stats": {}, "contract_notes": []}
    for key, default in defaults.items():
        if key not in out:
            value = payload.get(key)
            out[key] = default if value is None else value
    out["status"] = payload.get("status") or "partial"
    out["contract_notes"] = notes + list(payload.get("contract_notes") or [])
    return out


def split_units(text):
    units = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", block)
        if heading:
            units.append(("heading", heading.group(2).strip(), []))
            continue
        for sentence in re.split(r"(?<=[\u3002\uff01\uff1f\uff1b])|(?<=[.!?])(?=\s)", block):
            sentence = sentence.strip()
            if len(sentence) >= 15:
                units.append(("sentence", sentence, []))
    return units


def tokens(text):
    latin = [word for word in re.findall(r"[a-z][a-z0-9\-]{2,}", text.lower())
             if word not in {"the", "and", "for", "with", "that", "this", "were", "was",
                             "from", "have", "has", "are", "not", "but", "which", "into"}]
    cjk = []
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        cjk.extend(run[i:i + 2] for i in range(max(1, len(run) - 1)))
    return set(latin + cjk)


def parse_refs(case):
    for key in REF_KEYS:
        value = case.get(key)
        if isinstance(value, list) and value:
            refs = []
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    lowered = {str(k).lower(): v for k, v in item.items()}
                    ref = OrderedDict()
                    ref["id"] = str(lowered.get("key") or lowered.get("id") or "R%d" % (index + 1))
                    ref["title"] = str(lowered.get("title") or lowered.get("name") or "")
                    ref["year"] = str(lowered.get("year") or lowered.get("date") or "")
                    ref["type"] = str(lowered.get("type") or lowered.get("entry_type") or "")
                    ref["authors"] = str(lowered.get("authors") or lowered.get("author") or "")
                    body = (lowered.get("abstract") or lowered.get("summary") or lowered.get("findings")
                            or lowered.get("excerpt") or lowered.get("text") or "")
                    ref["excerpt"] = str(body)
                    ref["locator"] = "/" + key + "/" + str(index)
                    refs.append(ref)
                elif isinstance(item, str):
                    refs.append(OrderedDict([
                        ("id", "R%d" % (index + 1)), ("title", item.strip()),
                        ("year", (re.search(r"(19|20)\d{2}", item) or [""])[0] if re.search(r"(19|20)\d{2}", item) else ""),
                        ("type", ""), ("authors", ""), ("excerpt", item.strip()),
                        ("locator", "/" + key + "/" + str(index))]))
            return "/" + key, refs
    return "", []


def grade_ref(ref):
    blob = " ".join([ref.get("type", ""), ref.get("title", ""), ref.get("excerpt", "")])
    for name, grade, pattern in DESIGN_GRADES:
        if re.search(pattern, blob, flags=re.IGNORECASE):
            return name, grade
    return "unclassified", 2


def sample_size(ref):
    match = re.search(r"\bn\s*=\s*(\d+)|\b(\d+)\s+(?:participants|patients|subjects|samples|mice|rats)\b",
                      ref.get("excerpt", ""), flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1) or match.group(2))


def cited_numbers(claim):
    numbers = []
    for match in re.finditer(r"\[(\d+(?:\s*[,\-\u2013]\s*\d+)*)\]", claim):
        for part in re.split(r"[,\u3001]", match.group(1)):
            part = part.strip()
            if re.match(r"^\d+\s*[-\u2013]\s*\d+$", part):
                start, end = [int(value) for value in re.split(r"[-\u2013]", part)]
                numbers.extend(range(start, end + 1))
            elif part.isdigit():
                numbers.append(int(part))
    return numbers


def cited_keys(claim):
    return [item.strip() for match in re.finditer(r"\\cite[a-zA-Z]*\{([^}]+)\}", claim)
            for item in match.group(1).split(",")]


def classify_support(claim, refs):
    if not refs:
        return "unsupported"
    grades = [grade_ref(ref)[1] for ref in refs]
    best = max(grades)
    strong = bool(re.search(STRONG_VERBS, claim, flags=re.IGNORECASE))
    if best >= 4:
        return "strong"
    if best == 3:
        return "moderate_strong" if strong else "moderate"
    if best == 2:
        return "limited"
    return "weak"


INTENSIFIERS = r"\b(clearly|undoubtedly|obviously|definitely|certainly|always|never)\b\s*"


def suggested_revision(claim, support):
    if support in ("unsupported",):
        return claim + "（需补引用或删除断言）"
    if support in ("weak", "limited"):
        revised, reasons = claim, []
        if re.search(CAUSAL, claim, flags=re.IGNORECASE) and not re.search(HEDGES, claim, flags=re.IGNORECASE):
            def relink(match):
                verb = match.group(1).lower()
                return "are associated with" if verb in ("cause", "lead", "result") else "is associated with"
            revised = re.sub(r"\b(causes?|leads? to|results? in)\b", relink, revised,
                             flags=re.IGNORECASE)
            revised = re.sub(r"(导致|引起|造成)", "与…相关", revised)
            reasons.append("因果表述改为相关性表述")
        if re.search(STRONG_VERBS, claim, flags=re.IGNORECASE) and not re.search(HEDGES, claim, flags=re.IGNORECASE):
            revised = re.sub(r"\b(proves?|proven)\b", "may be", revised, flags=re.IGNORECASE)
            revised = re.sub(r"\b(demonstrates?|demonstrated)\b", "may indicate", revised,
                             flags=re.IGNORECASE)
            revised = re.sub(r"\b(confirms?|confirmed)\b", "is consistent with", revised,
                             flags=re.IGNORECASE)
            revised = re.sub(r"\bshows? that\b", "suggests that", revised, flags=re.IGNORECASE)
            reasons.append("强断言降级")
        if reasons:
            revised = re.sub(INTENSIFIERS, "", revised, flags=re.IGNORECASE)
            revised = re.sub(r"\s{2,}", " ", revised).strip()
            return revised + "（证据等级不足：%s）" % "，".join(reasons)
    return claim


def build_payload(case, task_text):
    pointer, refs = parse_refs(case)
    draft = ""
    draft_pointer = ""
    for key in TEXT_KEYS:
        value = case.get(key)
        if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
            draft = "\n\n".join(item for item in value if len(item.strip()) >= 15)
            draft_pointer = "/" + key
            break
        if isinstance(value, str) and len(value.strip()) >= 40:
            draft = value
            draft_pointer = "/" + key
            break
    if not draft:
        for key, value in case.items():
            if str(key).lower() in REF_KEYS:
                continue
            if isinstance(value, str) and len(value.strip()) >= 150:
                draft, draft_pointer = value, "/" + str(key)
                break
    if not draft and not refs:
        return {"status": "insufficient_input",
                "result": {"claims": [], "evidence_table": [], "draft": ""},
                "evidence": [], "uncertainty": ["既没有待审稿件，也没有文献证据库。"],
                "errors": [], "stats": {"claims": 0, "references": 0}}
    if not draft:
        return {"status": "partial",
                "result": {"claims": [], "evidence_table": [], "draft": "",
                           "evidence_library": [{"id": ref["id"], "grade": grade_ref(ref)[0]}
                                                for ref in refs]},
                "evidence": [], "uncertainty": ["只有文献库，没有待审稿件，无法生成论断—证据表。"],
                "errors": [], "stats": {"claims": 0, "references": len(refs)}}

    by_number = {index + 1: ref for index, ref in enumerate(refs)}
    by_key = {norm_key(ref["id"]): ref for ref in refs}
    units = split_units(draft)
    section = ""
    claims, evidence_rows, gaps, uncertainty = [], [], [], []
    claim_index = 0
    for kind, text, _ in units:
        if kind == "heading":
            section = text
            continue
        numbers = cited_numbers(text)
        keys = cited_keys(text)
        if not numbers and not keys:
            continue
        claim_index += 1
        claim_id = "C%02d" % claim_index
        bound, missing = [], []
        for number in numbers:
            ref = by_number.get(number)
            if ref:
                bound.append(ref)
            else:
                missing.append(number)
        for key in keys:
            ref = by_key.get(norm_key(key))
            if ref:
                bound.append(ref)
            else:
                missing.append(key)
        support = classify_support(text, bound)
        claim_tokens = tokens(text)
        evidence_entries = []
        for ref in bound:
            design, grade = grade_ref(ref)
            size = sample_size(ref)
            ref_tokens = tokens(ref.get("title", "") + " " + ref.get("excerpt", ""))
            overlap = len(claim_tokens & ref_tokens)
            topical = "aligned" if overlap >= 3 else ("weak_overlap" if overlap else "no_lexical_overlap")
            if topical != "aligned":
                gaps.append({"claim_id": claim_id, "reference": ref["id"], "issue": topical,
                             "detail": "论断与文献题名/摘要的词项重叠为 %d，需人工确认是否真的支持。" % overlap})
            evidence_entries.append(OrderedDict([
                ("reference", ref["id"]), ("locator", ref["locator"]),
                ("design", design), ("grade", grade),
                ("sample_size", size),
                ("topical_alignment", topical),
                ("lexical_overlap", overlap),
                ("note", "证据等级由研究设计与样本量启发式判定，需人工复核。")]))
        overclaim = bool(re.search(STRONG_VERBS, text, flags=re.IGNORECASE)) and support in ("weak", "limited", "moderate")
        causal = bool(re.search(CAUSAL, text, flags=re.IGNORECASE))
        correlation = bool(re.search(CORRELATION, text, flags=re.IGNORECASE))
        if causal and any(grade_ref(ref)[1] <= 2 for ref in bound):
            gaps.append({"claim_id": claim_id, "reference": None, "issue": "causal_language_on_weak_evidence",
                         "detail": "使用因果动词，但所引证据等级不超过 2。"})
        if overclaim:
            gaps.append({"claim_id": claim_id, "reference": None, "issue": "overclaim",
                         "detail": "强断言与证据等级（%s）不匹配。" % support})
        claim = OrderedDict([
            ("claim_id", claim_id), ("section", section), ("claim", text),
            ("citations", [item for item in ["[%d]" % n for n in numbers] + keys]),
            ("support_level", support),
            ("overclaim", overclaim),
            ("causal_language", causal),
            ("correlation_language", correlation),
            ("suggested_revision", suggested_revision(text, support)),
            ("evidence", evidence_entries),
            ("dangling_citations", missing),
        ])
        claims.append(claim)
        evidence_rows.extend(dict(row, claim_id=claim_id) for row in evidence_entries)
        if not bound:
            gaps.append({"claim_id": claim_id, "reference": None, "issue": "no_bound_evidence",
                         "detail": "引用的编号/键均未在文献库中找到。"})

    if not claims:
        uncertainty.append("稿件中没有检出任何带引用标记的论断；如需覆盖无引用断言，请提供 claims 列表。")
    unsupported = [claim["claim_id"] for claim in claims if claim["support_level"] == "unsupported"]
    if unsupported:
        uncertainty.append("%d 条论断没有可用证据（%s）。" % (len(unsupported), unsupported[:8]))
    weak = [claim["claim_id"] for claim in claims if claim["support_level"] in ("weak", "limited")]
    if weak:
        uncertainty.append("%d 条论断仅有弱证据或有限证据（%s），表述已建议降级。" % (len(weak), weak[:8]))
    if not refs:
        uncertainty.append("未提供文献证据库，所有引用均无法绑定，结论只做结构诊断。")
    if any(not ref.get("excerpt") for ref in refs):
        uncertainty.append("部分文献只有题名、没有摘要或原文片段，无法核验其是否支持具体论断。")

    result = {
        "claims": claims,
        "evidence_table": evidence_rows,
        "evidence_gaps": gaps,
        "unsupported_claims": unsupported,
        "draft": draft,
        "section_locations": [{"claim_id": claim["claim_id"], "section": claim["section"]}
                              for claim in claims],
        "strength_scale": "5=meta-analysis/systematic review, 4=RCT, 3=cohort/case-control, "
                          "2=cross-sectional/narrative review, 1=case report/preprint/in vitro",
        "limitations": ["证据等级为设计+样本量的启发式分级，不等于 GRADE 正式评级。",
                        "不做联网核验，无法判断文献真伪、撤稿或版本差异。",
                        "不自动改写全文，只给逐条论断的修订建议。"],
    }
    stats = {"claims": len(claims), "references": len(refs),
             "evidence_rows": len(evidence_rows), "gaps": len(gaps),
             "unsupported": len(unsupported), "weak": len(weak),
             "overclaims": sum(1 for claim in claims if claim["overclaim"]),
             "dangling_citations": sum(len(claim["dangling_citations"]) for claim in claims)}
    return {"status": "success", "result": result, "claims": claims,
            "evidence_table": evidence_rows, "draft": draft,
            "evidence": [{"claim_id": claim["claim_id"], "section": claim["section"],
                          "locator": draft_pointer, "claim": clamp(claim["claim"], 200)}
                         for claim in claims],
            "uncertainty": uncertainty, "errors": [], "stats": stats}


def main():
    parser = argparse.ArgumentParser(description="Evidence-driven claim auditing")
    parser.add_argument("--case", default=DEFAULT_CASE)
    parser.add_argument("--out", "--output", dest="out", default=DEFAULT_OUT)
    parser.add_argument("--work", default=DEFAULT_WORK)
    args = parser.parse_args()
    stage, case = "load_case", {}
    try:
        if not os.path.isfile(args.case):
            raise FileNotFoundError("case file not found: %s" % os.path.basename(args.case))
        case = load_json(args.case)
        if not isinstance(case, dict):
            raise ValueError("case.json must contain a JSON object")
        stage = "build_payload"
        contract = None
        for key in ("output_contract", "outputContract", "output_schema"):
            if isinstance(case.get(key), (dict, list)):
                contract = case[key]
                break
        payload = build_payload(case, find_task_text(args.case))
        output = finalize(case, payload, contract)
        stage = "write_output"
        directory = os.path.dirname(os.path.abspath(args.out))
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(output, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        sys.stdout.write(json.dumps({"case_id": output.get("case_id"),
                                     "status": output.get("status"),
                                     "claims": output.get("stats", {}).get("claims"),
                                     "contract_fields": len(contract_fields(contract))},
                                    ensure_ascii=False) + "\n")
        return 0
    except Exception as exc:
        failure = OrderedDict([
            ("case_id", case.get("case_id") or case.get("id")), ("status", "failed"),
            ("result", {"claims": [], "evidence_table": [], "draft": ""}), ("evidence", []),
            ("uncertainty", ["运行失败，未产出证据表；未重试、未编造证据。"]),
            ("errors", [{"stage": stage, "type": type(exc).__name__,
                         "message": clamp(str(exc), 400)}]),
            ("stats", {}), ("contract_notes", [])])
        try:
            directory = os.path.dirname(os.path.abspath(args.out))
            if directory and not os.path.isdir(directory):
                os.makedirs(directory)
            with open(args.out, "w", encoding="utf-8") as handle:
                json.dump(failure, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except OSError:
            pass
        sys.stdout.write(json.dumps({"status": "failed", "stage": stage},
                                    ensure_ascii=False) + "\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
