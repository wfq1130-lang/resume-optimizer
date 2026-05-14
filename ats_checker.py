"""ATS 兼容性检查 — 模拟企业招聘系统对简历的机器评分规则"""

import re
from resume_structure import parse_structure

# ATS-friendly action verbs (Chinese + English)
ACTION_VERBS_CN = [
    "负责", "主导", "领导", "管理", "设计", "开发", "实现", "优化", "提升",
    "降低", "完成", "达成", "创建", "构建", "推进", "协调", "制定", "执行",
    "分析", "解决", "改进", "重建", "部署", "交付", "整合", "推动", "带领",
    "建立", "发起", "规划", "统筹", "撰写", "培训", "指导", "评估", "监控",
]

ACTION_VERBS_EN = [
    "led", "managed", "developed", "designed", "implemented", "created",
    "optimized", "reduced", "increased", "achieved", "delivered", "launched",
    "built", "directed", "coordinated", "executed", "analyzed", "resolved",
    "improved", "deployed", "integrated", "spearheaded", "established",
    "orchestrated", "automated", "engineered", "architected", "generated",
]

# Keywords ATS looks for in different industries
INDUSTRY_KEYWORDS = {
    "tech": ["python", "java", "javascript", "react", "aws", "docker", "kubernetes",
             "sql", "agile", "scrum", "api", "cloud", "devops", "ci/cd", "git",
             "machine learning", "data", "微服务", "分布式", "高并发"],
    "finance": ["财务分析", "风险控制", "预算", "审计", "合规", "税务", "现金流",
                "financial", "risk", "audit", "compliance", "budget", "forecast"],
    "marketing": ["增长", "用户增长", "转化率", "投放", "品牌", "内容营销", "seo",
                  "社交媒体", "roi", "cac", "ltv", "campaign", "channel"],
    "sales": ["客户关系", "销售策略", "营收", "谈判", "渠道", "客户管理", "pipeline",
              "quota", "negotiation", "account", "bd", "partnership"],
    "hr": ["招聘", "绩效", "培训", "薪酬", "员工关系", "组织发展", "hrbp",
           "recruitment", "performance", "compensation", "talent"],
}

# Quantifiable metric patterns
QUANT_PATTERNS = [
    r"\d+%", r"\d+\s*万", r"\d+\s*亿", r"\d+\s*倍",
    r"\$\d+", r"USD\s*\d+", r"人民币\s*\d+",
    r"\d+\s*人", r"\d+\s*个", r"\d+\s*项", r"\d+\s*次",
    r"\d+\s*[kK]", r"\d+\s*[mM]", r"increased by \d+", r"reduced by \d+",
    r"from \d+ to \d+", r"增长\s*\d+", r"降低\s*\d+",
]


def check_ats(resume_text, jd_text=""):
    """全面 ATS 兼容性检查，返回详细评分和修复建议。"""
    structure = parse_structure(resume_text)
    sections = structure["sections"]
    personal = structure["personal_info"]
    stats = structure["stats"]

    jd_keywords = _extract_jd_keywords(jd_text) if jd_text else []

    checks = {}
    total = 0

    # 1. Contact info completeness (15 pts)
    score, detail = _check_contact(personal)
    checks["contact_info"] = {"score": score, "max": 15, "detail": detail}
    total += score

    # 2. Section completeness (20 pts)
    score, detail = _check_sections(sections, stats)
    checks["section_completeness"] = {"score": score, "max": 20, "detail": detail}
    total += score

    # 3. ATS-unfriendly elements (15 pts) — tables, images, special chars
    score, detail = _check_format_friendliness(resume_text)
    checks["format_friendliness"] = {"score": score, "max": 15, "detail": detail}
    total += score

    # 4. Action verbs usage (10 pts)
    score, detail = _check_action_verbs(resume_text)
    checks["action_verbs"] = {"score": score, "max": 10, "detail": detail}
    total += score

    # 5. Quantifiable achievements (15 pts)
    score, detail = _check_quantification(resume_text)
    checks["quantification"] = {"score": score, "max": 15, "detail": detail}
    total += score

    # 6. Length check (10 pts)
    score, detail = _check_length(resume_text)
    checks["length"] = {"score": score, "max": 10, "detail": detail}
    total += score

    # 7. Keyword density (15 pts)
    score, detail = _check_keywords(resume_text, jd_keywords)
    checks["keyword_density"] = {"score": score, "max": 15, "detail": detail}
    total += score

    # Overall score (100 pts)
    grade = "A+" if total >= 95 else "A" if total >= 85 else "B" if total >= 70 else "C" if total >= 55 else "D"
    fix_actions = _generate_fix_actions(checks, total)

    return {
        "total_score": total,
        "grade": grade,
        "checks": checks,
        "fix_actions": fix_actions,
        "structure": {
            "sections_found": [k for k, v in sections.items() if v],
            "sections_missing": stats["missing_sections"],
            "personal_info": personal,
            "skills_detected": structure["skills_list"][:20],
        },
    }


def _extract_jd_keywords(jd_text):
    """从 JD 中提取关键词"""
    if not jd_text:
        return []

    # Extract from all industry keyword pools
    found = set()
    lower_jd = jd_text.lower()
    for pool in INDUSTRY_KEYWORDS.values():
        for kw in pool:
            if kw.lower() in lower_jd:
                found.add(kw.lower())

    # Also extract CAPITALIZED terms and "N+ years" patterns
    caps = re.findall(r"\b[A-Z]{2,}(?:\s+[A-Z]{2,})*\b", jd_text)
    for c in caps:
        if len(c) >= 3:
            found.add(c.lower())

    years = re.findall(r"(\d+[\+]?\s*年|(\d+[-~]\d+)\s*年)", jd_text)
    for y in years:
        found.add(y[0])

    return sorted(found)


def _check_contact(personal):
    detail = []
    score = 0
    if personal["name"]:
        score += 4
    else:
        detail.append("缺少姓名")
    if personal["phone"]:
        score += 4
    else:
        detail.append("缺少手机号 — ATS可能无法联系到你")
    if personal["email"]:
        score += 4
    else:
        detail.append("缺少邮箱 — 大部分ATS要求邮箱")
    # LinkedIn/GitHub bonus
    score += 3  # can't verify from text alone, give partial
    if not detail:
        detail.append("联系方式完整")
    return score, detail


def _check_sections(sections, stats):
    required = {"education": 5, "experience": 7, "skills": 4}
    optional = {"projects": 2, "certifications": 1, "languages": 1}

    score = 0
    detail = []

    for key, pts in required.items():
        if sections.get(key):
            score += pts
        else:
            detail.append(f"缺少「{_section_label(key)}」模块 — ATS 筛选时可能直接淘汰")

    for key, pts in optional.items():
        if sections.get(key):
            score += pts

    if not detail:
        detail.append("核心模块完整")
    return score, detail


def _check_format_friendliness(text):
    score = 15
    deductions = []

    # Tables (indicated by | delimiters)
    if text.count("|") > 10:
        ded = min(5, text.count("|") // 5)
        score -= ded
        deductions.append(f"检测到表格分隔符 — ATS 无法解析表格内容 (扣{ded}分)")

    # Special unicode characters that ATS may mangle
    specials = ["●", "○", "◆", "◇", "■", "□", "→", "⇒", "➤", "✓", "✔"]
    found_specials = [c for c in specials if c in text]
    if found_specials:
        ded = min(3, len(found_specials))
        score -= ded
        deductions.append(f"包含特殊符号 {''.join(found_specials[:5])} — ATS可能显示为乱码 (扣{ded}分)")

    # Columns/spacing issues — multiple consecutive spaces
    if re.search(r" {4,}", text):
        score -= 3
        deductions.append("存在多余空格或列对齐 — 部分ATS会截断内容 (扣3分)")

    if not deductions:
        deductions.append("格式规范，未发现ATS不兼容元素")
    return max(0, score), deductions


def _check_action_verbs(text):
    cn_count = sum(1 for v in ACTION_VERBS_CN if v in text)
    en_count = sum(1 for v in ACTION_VERBS_EN if v.lower() in text.lower())
    total_verbs = cn_count + en_count

    if total_verbs >= 10:
        return 10, [f"使用了 {total_verbs} 个行为动词 — 优秀"]
    elif total_verbs >= 5:
        return 7, [f"使用了 {total_verbs} 个行为动词 — 建议增加到10个以上"]
    elif total_verbs >= 2:
        return 4, [f"仅有 {total_verbs} 个行为动词 — ATS偏好主动语态的描述"]
    else:
        return 1, ["几乎没有行为动词 — 建议开头用「负责/主导/开发/优化」等动词"]


def _check_quantification(text):
    matches = []
    for pat in QUANT_PATTERNS:
        found = re.findall(pat, text)
        if isinstance(found[0], tuple) if found else False:
            found = [f[0] for f in found]
        matches.extend(found)

    unique = len(set(matches))
    if unique >= 8:
        return 15, [f"检测到 {unique}+ 处量化成果 — 数据驱动，ATS高分"]
    elif unique >= 4:
        return 10, [f"检测到 {unique} 处量化指标 — 建议增加数据支撑"]
    elif unique >= 1:
        return 5, [f"仅 {unique} 处量化 — ATS偏好可衡量的成果 (提升X%, 降低Y万)"]
    else:
        return 1, ["未检测到任何量化数据 — 建议添加数字(如提升30%、管理10人团队)"]


def _check_length(text):
    chars = len(text)
    # Ideal: 3000-8000 chars ~ 1-2 pages
    if 3000 <= chars <= 8000:
        return 10, [f"长度 {chars} 字 — 1-2页，ATS最佳范围"]
    elif 2000 <= chars < 3000:
        return 7, [f"长度 {chars} 字 — 偏短，建议扩充到3000字以上"]
    elif chars < 2000:
        return 4, [f"长度 {chars} 字 — 过短，内容不足以通过ATS筛选"]
    elif 8000 < chars <= 12000:
        return 6, [f"长度 {chars} 字 — 偏长，2页以上部分ATS可能截断"]
    else:
        return 3, [f"长度 {chars} 字 — 过长，建议精简到2页以内"]


def _check_keywords(text, jd_keywords):
    if not jd_keywords:
        return 5, ["未提供JD关键词 — 无法评估关键词匹配度 (基础分5/15)"]

    lower_text = text.lower()
    matched = [kw for kw in jd_keywords if kw.lower() in lower_text]
    missing = [kw for kw in jd_keywords if kw.lower() not in lower_text]

    rate = len(matched) / len(jd_keywords) if jd_keywords else 0

    if rate >= 0.8:
        score = 15
    elif rate >= 0.6:
        score = 12
    elif rate >= 0.4:
        score = 8
    elif rate >= 0.2:
        score = 5
    else:
        score = 2

    detail = [f"匹配 {len(matched)}/{len(jd_keywords)} 个JD关键词 ({int(rate*100)}%)"]
    if missing:
        detail.append(f"缺失关键词: {', '.join(missing[:8])}")
    return score, detail


def _generate_fix_actions(checks, total):
    """生成优先级排序的修复建议"""
    actions = []

    for name, check in checks.items():
        if check["score"] < check["max"] * 0.7:
            label = {
                "contact_info": "补全联系方式",
                "section_completeness": "完善简历模块结构",
                "format_friendliness": "修复ATS格式兼容问题",
                "action_verbs": "增加行为动词",
                "quantification": "添加量化成果数据",
                "length": "调整简历长度",
                "keyword_density": "补充缺失的关键词",
            }.get(name, name)

            actions.append({
                "category": name,
                "label": label,
                "score": check["score"],
                "max": check["max"],
                "detail": check["detail"],
            })

    actions.sort(key=lambda a: a["score"] / a["max"])
    return actions


def _section_label(key):
    return {
        "education": "教育背景",
        "experience": "工作经历",
        "skills": "技能",
        "projects": "项目经验",
        "certifications": "证书",
        "languages": "语言能力",
    }.get(key, key)
