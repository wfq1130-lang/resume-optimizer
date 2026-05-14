"""简历结构化解析 — 识别教育、工作、技能、项目等模块"""

import re


def parse_structure(text):
    """将简历纯文本解析为结构化模块。返回 dict 包含各 section 文本。"""
    sections = {
        "personal": "",
        "summary": "",
        "education": "",
        "experience": "",
        "projects": "",
        "skills": "",
        "certifications": "",
        "languages": "",
    }

    lines = text.split("\n")
    current = None
    buffers = {k: [] for k in sections}

    # Section header patterns (ordered by priority)
    patterns = [
        ("summary", r"(个人简介|自我评价|个人总结|求职意向|关于我|SUMMARY|PROFILE|OBJECTIVE)",
         r"(教育|学历|学习经历|学校|毕业|EDUCATION)"),
        ("education", r"(教育背景|学历|学习经历|教育经历|EDUCATION)",
         r"(工作|实习|项目|技能|证书|语言|WORK|EXPERIENCE|PROJECT|SKILL)"),
        ("experience", r"(工作经历|实习经历|工作经验|从业经历|WORK|EXPERIENCE|EMPLOYMENT)",
         r"(教育|项目|技能|证书|语言|EDUCATION|PROJECT|SKILL|CERTIFICAT)"),
        ("projects", r"(项目经验|项目经历|主要项目|参与项目|PROJECT|PORTFOLIO)",
         r"(教育|工作|技能|证书|语言|EDUCATION|WORK|SKILL|CERTIFICAT)"),
        ("skills", r"(专业技能|技术栈|擅长技能|技能特长|SKILL|TECHNICAL|技术能力)",
         r"(教育|工作|项目|证书|语言|EDUCATION|WORK|PROJECT|CERTIFICAT|LANGUAGE)"),
        ("certifications", r"(证书|资格证书|所获证书|CERTIFICAT|LICENSE)",
         r"(教育|工作|项目|技能|语言|EDUCATION|WORK|PROJECT|SKILL|LANGUAGE)"),
        ("languages", r"(语言能力|外语|LANGUAGE)",
         r"(教育|工作|项目|技能|证书|EDUCATION|WORK|PROJECT|SKILL|CERTIFICAT)"),
    ]

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current:
                buffers[current].append("")
            continue

        # Check if this line is a section header
        matched = None
        for key, start_pat, _end_pat in patterns:
            if re.search(start_pat, stripped, re.IGNORECASE):
                if len(stripped) < 60 and not stripped.endswith((".", "。", ":", "：")) or len(stripped) < 20:
                    matched = key
                    break

        if matched:
            current = matched
            continue

        if current:
            buffers[current].append(stripped)
        else:
            buffers["personal"].append(stripped)

    # Assemble sections
    for k in sections:
        sections[k] = "\n".join(buffers[k]).strip()

    # Extract personal info from top section
    personal_info = _extract_personal(sections["personal"])

    # Extract skills list
    skills_list = _extract_skills_list(sections["skills"])

    return {
        "sections": sections,
        "personal_info": personal_info,
        "skills_list": skills_list,
        "stats": _compute_stats(sections),
    }


def _extract_personal(text):
    """从个人信息区域提取姓名/手机/邮箱"""
    info = {"name": "", "phone": "", "email": ""}

    lines = text.split("\n")[:8]

    for line in lines:
        # Phone
        phone_match = re.search(r"1[3-9]\d{9}", line)
        if phone_match and not info["phone"]:
            info["phone"] = phone_match.group()

        # Email
        email_match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", line)
        if email_match and not info["email"]:
            info["email"] = email_match.group()

    # Name: first non-empty, short line without special chars (likely the name)
    for line in lines:
        stripped = line.strip()
        if stripped and len(stripped) <= 10 and not re.search(r"[@\d:]", stripped):
            if not re.search(r"(简历|个人|联系|电话|邮箱|求职|RESUME|CV|PHONE|EMAIL)", stripped, re.IGNORECASE):
                info["name"] = stripped
                break

    return info


def _extract_skills_list(text):
    """从技能区域提取技能关键词列表"""
    skills = set()
    # Split by common delimiters
    for part in re.split(r"[,，/、\|\\\n;；]", text):
        skill = part.strip()
        if 2 <= len(skill) <= 30 and not re.match(r"^[\d\s\.]+$", skill):
            skills.add(skill.lower())
    return sorted(skills)


def _compute_stats(sections):
    """统计各模块基本信息"""
    stats = {}
    for key, text in sections.items():
        words = len(text.split()) if text else 0
        chars = len(text)
        stats[key] = {"words": words, "chars": chars, "empty": not bool(text)}
    total_chars = sum(v["chars"] for v in stats.values())
    total_words = sum(v["words"] for v in stats.values())
    missing = [k for k, v in stats.items() if v.get("empty")]
    stats["total_chars"] = total_chars
    stats["total_words"] = total_words
    stats["missing_sections"] = missing
    return stats
