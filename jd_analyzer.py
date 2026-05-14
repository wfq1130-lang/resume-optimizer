"""JD 深度解析与简历定向优化 — 结构化提取JD需求，精准匹配简历缺口"""

import re, json
import requests, os

from resume_structure import parse_structure

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

JD_PARSE_PROMPT = """你是一位资深招聘专家。请解析以下职位描述(JD)，严格按照JSON格式返回：

{
  "title": "职位名称",
  "hard_skills": ["技能1", "技能2", ...],
  "soft_skills": ["沟通能力", ...],
  "experience_years": "3-5年",
  "education": "本科及以上",
  "must_have": ["必须满足的要求"],
  "nice_to_have": ["加分项"],
  "responsibilities": ["主要职责1", ...]
}

规则：
- hard_skills: 技术栈、工具、证书等可量化技能
- soft_skills: 沟通、领导力等软技能
- experience_years: 工作年限要求
- education: 学历要求
- must_have: 必须项（不超过6条）
- nice_to_have: 加分项（不超过5条）
- 不要编造JD中没有的内容"""


TARGETED_REWRITE_PROMPT = """你是一位顶尖的简历顾问和ATS优化专家。你的任务是在保持真实性的前提下，将简历针对特定职位描述进行定向优化。

## 原始简历
{resume_text}

## 目标职位描述
{jd_text}

## JD 需求分析
- 硬技能要求: {hard_skills}
- 软技能要求: {soft_skills}
- 必须项: {must_have}
- 加分项: {nice_to_have}

## 简历与JD的差距
{gap_analysis}

## 优化规则
1. **绝不编造经历** — 只能基于原有经历优化措辞和侧重点
2. **自然融入缺失关键词** — 如果简历中有相关但不显眼的经验，突出它；如果完全没有，不要生造
3. **使用JD中的术语** — 将简历中的同义表达替换为JD中的术语
4. **重排经历顺序** — 把与JD最相关的项目/经历放在最前面
5. **量化已有成果** — 如果原文有模糊描述，尝试补充合理的量化
6. **保留真实信息** — 姓名、公司名、日期、职位绝不要改

请严格按照以下JSON格式返回：
{{
  "optimized_resume": "定向优化后的完整简历...",
  "changes_summary": ["具体改动1", "具体改动2", ...],
  "keyword_coverage": 85,
  "ats_score_estimate": 88
}}
"""


def parse_jd(jd_text):
    """解析JD，返回结构化需求"""
    if not DEEPSEEK_API_KEY:
        return _parse_jd_rules(jd_text)

    try:
        result = _call_ai(JD_PARSE_PROMPT, jd_text, max_tokens=2048)
        return result
    except Exception:
        return _parse_jd_rules(jd_text)


def _parse_jd_rules(jd_text):
    """规则兜底：用正则粗略解析JD"""
    reqs = {}

    # Extract years
    year_match = re.search(r"(\d+[-~]\d+)\s*年", jd_text)
    if year_match:
        reqs["experience_years"] = year_match.group(1) + "年"
    else:
        reqs["experience_years"] = "不限"

    # Education
    edu_patterns = ["本科", "硕士", "博士", "大专", "学历不限", "本科及以上", "硕士及以上"]
    reqs["education"] = "不限"
    for ep in edu_patterns:
        if ep in jd_text:
            reqs["education"] = ep
            break

    # Extract skills keywords
    tech_keywords = [
        "python", "java", "javascript", "react", "vue", "angular", "node", "go",
        "rust", "c++", "typescript", "docker", "kubernetes", "aws", "sql", "mysql",
        "postgresql", "redis", "mongodb", "elasticsearch", "kafka", "rabbitmq",
        "spring", "django", "flask", "fastapi", "git", "linux", "tensorflow",
        "pytorch", "spark", "hadoop", "airflow", "tableau", "power bi", "excel",
        "figma", "sketch", "photoshop", "illustrator", "jira", "confluence",
        "机器学习", "深度学习", "数据分析", "数据挖掘", "微服务", "分布式",
        "高并发", "性能优化", "项目管理", "产品设计", "用户研究",
    ]
    found_skills = []
    lower_jd = jd_text.lower()
    for sk in tech_keywords:
        if sk.lower() in lower_jd:
            found_skills.append(sk)

    # Soft skills
    soft_keywords = ["沟通", "团队合作", "领导力", "解决问题", "抗压", "自驱",
                     "逻辑思维", "ownership", "cross-functional", "stakeholder",
                     "negotiation", "presentation"]
    found_soft = [s for s in soft_keywords if s.lower() in lower_jd]

    # Must-have: sentences containing "必须"，"要求"，"需要"，"require"
    must_lines = re.findall(r"[^。]*?(?:必须|要求|需要|require|must)[^。]*[。]?", jd_text, re.IGNORECASE)
    must_have = [m.strip() for m in must_lines[:5]]

    reqs.update({
        "title": "",
        "hard_skills": found_skills[:12],
        "soft_skills": found_soft[:6],
        "must_have": must_have,
        "nice_to_have": [],
        "responsibilities": [],
    })
    return reqs


def analyze_gap(resume_text, jd_requirements):
    """对比简历和JD需求，找出差距"""
    structure = parse_structure(resume_text)
    sections = structure["sections"]
    skills_text = sections["skills"].lower() + " " + sections["experience"].lower()
    resume_lower = resume_text.lower()

    gaps = []
    matches = []

    # Check hard skills
    hard_skills = jd_requirements.get("hard_skills", [])
    for sk in hard_skills:
        if sk.lower() in resume_lower:
            matches.append(sk)
        else:
            gaps.append({"type": "hard_skill", "keyword": sk, "severity": "high"})

    # Check soft skills
    soft_skills = jd_requirements.get("soft_skills", [])
    for sk in soft_skills:
        if sk.lower() in resume_lower:
            matches.append(sk)
        else:
            gaps.append({"type": "soft_skill", "keyword": sk, "severity": "medium"})

    # Check must-have requirements
    must_have = jd_requirements.get("must_have", [])
    for mh in must_have:
        matched = _fuzzy_match_requirement(mh, resume_text)
        if not matched:
            gaps.append({"type": "requirement", "keyword": mh[:80], "severity": "high"})

    # Section gaps
    for key in ["projects", "certifications"]:
        if not sections.get(key):
            gaps.append({"type": "section", "keyword": key, "severity": "low"})

    coverage = len(matches) / (len(hard_skills) + len(soft_skills)) if (hard_skills or soft_skills) else 0

    return {
        "matches": list(set(matches)),
        "gaps": gaps,
        "coverage_pct": round(coverage * 100),
        "high_severity_count": sum(1 for g in gaps if g["severity"] == "high"),
        "total_gaps": len(gaps),
    }


def _fuzzy_match_requirement(req_text, resume_text):
    """Check if a requirement is roughly satisfied by the resume"""
    keywords = re.findall(r"[\w一-鿿]+", req_text)
    matched = sum(1 for kw in keywords if kw.lower() in resume_text.lower())
    return matched >= len(keywords) * 0.4


def generate_targeted_resume(resume_text, jd_text):
    """生成针对特定JD的定向优化简历"""
    jd_reqs = parse_jd(jd_text)
    gap = analyze_gap(resume_text, jd_reqs)

    # Build gap analysis text
    gap_lines = []
    high_gaps = [g for g in gap["gaps"] if g["severity"] == "high"]
    medium_gaps = [g for g in gap["gaps"] if g["severity"] == "medium"]

    if high_gaps:
        missing_keywords = [g["keyword"] for g in high_gaps if g["type"] == "hard_skill"]
        if missing_keywords:
            gap_lines.append(f"严重缺失的技能关键词: {', '.join(missing_keywords[:10])}")
        req_gaps = [g["keyword"] for g in high_gaps if g["type"] == "requirement"]
        if req_gaps:
            gap_lines.append(f"未满足的硬性要求: {'; '.join(req_gaps[:5])}")
    if medium_gaps:
        soft_missing = [g["keyword"] for g in medium_gaps if g["type"] == "soft_skill"]
        if soft_missing:
            gap_lines.append(f"可强化的软技能: {', '.join(soft_missing[:5])}")

    if not gap_lines:
        gap_lines.append("简历与JD匹配度较高，主要进行术语优化和重点突出")
    gap_lines.append(f"已匹配关键词: {', '.join(gap['matches'][:15])}")

    gap_text = "\n".join(f"- {line}" for line in gap_lines)

    prompt = TARGETED_REWRITE_PROMPT.format(
        resume_text=resume_text[:4000],
        jd_text=jd_text[:3000],
        hard_skills=", ".join(jd_reqs.get("hard_skills", [])[:10]),
        soft_skills=", ".join(jd_reqs.get("soft_skills", [])[:6]),
        must_have=", ".join(jd_reqs.get("must_have", [])[:6]),
        nice_to_have=", ".join(jd_reqs.get("nice_to_have", [])[:5]),
        gap_analysis=gap_text,
    )

    if not DEEPSEEK_API_KEY:
        return {
            "optimized_resume": "",
            "changes_summary": ["未配置AI API密钥，无法生成定向简历"],
            "keyword_coverage": gap["coverage_pct"],
            "ats_score_estimate": None,
            "gap_analysis": gap,
            "jd_requirements": jd_reqs,
        }

    try:
        result = _call_ai(prompt, prompt, max_tokens=4096, temperature=0.4)
        result["gap_analysis"] = gap
        result["jd_requirements"] = jd_reqs
        return result
    except Exception as e:
        return {
            "optimized_resume": "",
            "changes_summary": [f"AI生成失败: {str(e)}"],
            "keyword_coverage": gap["coverage_pct"],
            "ats_score_estimate": None,
            "gap_analysis": gap,
            "jd_requirements": jd_reqs,
        }


def _call_ai(system_prompt, user_message, max_tokens=4096, temperature=0.3):
    url = f"{DEEPSEEK_BASE_URL}/v1/chat/completions"
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return json.loads(data["choices"][0]["message"]["content"])
