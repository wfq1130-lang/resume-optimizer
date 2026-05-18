"""AI 简历分析 — 调用 DeepSeek API (with retry)"""

import json, os, re, time, logging
import requests

logger = logging.getLogger(__name__)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

RESUME_SYSTEM_PROMPT = """你是一位资深的HR专家和简历顾问，拥有10年以上招聘经验。你的任务是对简历进行深度分析。

请严格按照以下JSON格式返回分析结果（不要返回其他内容）：
{
  "overall_score": 85,
  "scores": {
    "内容完整度": 80,
    "措辞专业度": 85,
    "格式规范性": 90,
    "亮点突出度": 82,
    "量化成果": 75
  },
  "suggestions": [
    "具体建议1...",
    "具体建议2..."
  ],
  "optimized_resume": "优化后的完整简历文本..."
}

评分标准：
- 90-100：优秀，内容完整、措辞专业、有量化成果
- 75-89：良好，基本完整但部分可优化
- 60-74：一般，有较多可改进空间
- 60以下：较差，需要大幅修改

建议要求：
- 给出5-8条具体、可操作的修改建议
- 每条建议要具体，指出问题在哪里、怎么改
- 按重要性排序

优化简历要求：
- 保留原简历的真实信息，不要编造
- 优化措辞，使用更有力的动词
- 突出量化成果
- 改善格式和结构"""

JD_MATCH_SYSTEM_PROMPT = """你是一位资深的HR专家。你的任务是对比简历和职位描述(JD)，给出匹配度分析。

请严格按照以下JSON格式返回分析结果（不要返回其他内容）：
{
  "match_score": 75,
  "matched_points": [
    "匹配点1...",
    "匹配点2..."
  ],
  "gap_points": [
    "差距点1...",
    "差距点2..."
  ],
  "improvement_plan": "针对这个JD的具体改进建议...",
  "interview_tips": "针对这个岗位的面试准备建议..."
}
"""


def _call_deepseek(system_prompt, user_message, temperature=0.3, max_tokens=4096, retries=3):
    """调用 DeepSeek API with exponential backoff retry, 返回解析后的 JSON"""
    if not DEEPSEEK_API_KEY:
        return {"error": "未配置 DeepSeek API Key，请设置 DEEPSEEK_API_KEY 环境变量"}

    url = f"{DEEPSEEK_BASE_URL}/v1/chat/completions"
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"}
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }

    last_error = None
    for attempt in range(retries):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=180)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
        except requests.exceptions.Timeout:
            last_error = "AI 服务响应超时"
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else 0
            if status in (429, 502, 503, 504):
                wait = 2 ** attempt
                logger.warning("DeepSeek API %d, retrying in %ds (attempt %d/%d)", status, wait, attempt + 1, retries)
                time.sleep(wait)
                continue
            last_error = f"AI 服务请求失败: {e}"
            break
        except requests.exceptions.RequestException as e:
            wait = 2 ** attempt
            logger.warning("DeepSeek API connection error, retrying in %ds", wait)
            time.sleep(wait)
            continue
        except json.JSONDecodeError:
            logger.warning("DeepSeek returned invalid JSON, retrying")
            continue
        except Exception as e:
            last_error = f"分析失败: {e}"
            break

    if last_error:
        return {"error": last_error}
    return {"error": "AI 服务暂时不可用，请稍后重试"}


def analyze_resume(resume_text):
    """分析简历"""
    user_msg = f"请分析以下简历内容：\n\n{resume_text}"
    result = _call_deepseek(RESUME_SYSTEM_PROMPT, user_msg, temperature=0.3, max_tokens=4096)

    if "error" in result:
        return result

    # 规范化字段名
    return {
        "overall_score": result.get("overall_score", 0),
        "scores": result.get("scores", {}),
        "suggestions": result.get("suggestions", []),
        "optimized_resume": result.get("optimized_resume", "")
    }


GENERATE_SYSTEM_PROMPT = """你是一位资深的简历专家和职业顾问。你的任务是根据用户提供的信息，生成一份专业、完整的简历。

请严格按照以下JSON格式返回结果（不要返回其他内容）：
{
  "resume_text": "生成的完整简历...",
  "tips": "针对这类求职者的补充建议..."
}

简历要求：
- 即使信息有限，也要生成一份结构完整、内容合理的简历
- 使用专业的措辞和行业术语
- 突出用户的优势和潜力
- 格式清晰，包含个人信息、求职意向、教育背景、工作/实习经历、项目经验、技能证书等模块
- 如果用户没有提供某些信息，用 [] 标注留空让用户自行填写
- 量化成果，使用有力的动词"""

def generate_resume(user_input, scene=""):
    """根据用户描述生成简历"""
    scene_hints = {
        "fresh_graduate": "用户是应届毕业生，请重点挖掘校园经历、实习、项目、竞赛，突出学习能力和潜力。",
        "career_change": "用户正在转行，请重点突出可迁移能力，用目标行业的语言重构经历。",
        "experienced": "用户有多年经验，请突出核心竞争力和量化成果，展示职业成长轨迹。",
        "promotion": "用户寻求晋升，请突出管理能力、团队协作、业务影响力和领导潜质。",
    }
    scene_extra = scene_hints.get(scene, "")

    user_msg = f"用户描述：{user_input}\n\n{scene_extra}"
    result = _call_deepseek(GENERATE_SYSTEM_PROMPT, user_msg, temperature=0.6, max_tokens=4096)

    if "error" in result:
        return result

    return {
        "resume_text": result.get("resume_text", ""),
        "tips": result.get("tips", "")
    }


def match_jd(resume_text, jd_text):
    """匹配简历和JD"""
    user_msg = f"""简历内容：
{resume_text}

职位描述(JD)：
{jd_text}

请对比以上简历和JD，给出匹配度分析。"""

    result = _call_deepseek(JD_MATCH_SYSTEM_PROMPT, user_msg, temperature=0.3, max_tokens=3072)

    if "error" in result:
        return result

    return {
        "match_score": result.get("match_score", 0),
        "matched_points": result.get("matched_points", []),
        "gap_points": result.get("gap_points", []),
        "improvement_plan": result.get("improvement_plan", ""),
        "interview_tips": result.get("interview_tips", "")
    }


INTERVIEW_SYSTEM_PROMPT = """你是一位资深HR面试官，拥有10年以上面试经验。根据JD和简历生成针对性面试题。

请严格按照以下JSON格式返回：
{
  "technical_questions": [{"question": "...", "purpose": "考察什么能力", "suggested_answer": "参考答案要点"}],
  "behavioral_questions": [{"question": "...", "purpose": "考察什么", "suggested_answer": "参考要点"}],
  "self_intro_script": "针对该岗位的自我介绍脚本...",
  "salary_tips": "薪资谈判建议...",
  "overall_rating": 85,
  "preparation_tips": ["准备建议1", "准备建议2"]
}
"""


def simulate_interview(resume_text, jd_text):
    """根据简历和JD生成AI面试模拟"""
    if not DEEPSEEK_API_KEY:
        return {"error": "未配置AI API密钥"}
    user_msg = f"简历内容:\n{resume_text[:3000]}\n\n职位描述:\n{jd_text[:3000]}"
    result = _call_deepseek(INTERVIEW_SYSTEM_PROMPT, user_msg, temperature=0.5, max_tokens=4096)
    return result


ENGLISH_RESUME_PROMPT = """你是一位双语简历专家。将中文简历优化为英文简历，同时保持ATS兼容。

返回JSON格式：
{
  "english_resume": "完整的英文简历...",
  "chinese_resume": "同步优化的中文简历...",
  "key_translations": [{"cn": "中文术语", "en": "英文翻译"}],
  "culture_notes": ["文化差异提示1"]
}
"""


def optimize_english_resume(resume_text, jd_text=""):
    """将中文简历优化为英文简历"""
    if not DEEPSEEK_API_KEY:
        return {"error": "未配置AI API密钥"}
    jd_hint = f"\n目标职位描述:\n{jd_text[:2000]}" if jd_text else ""
    user_msg = f"简历:\n{resume_text[:4000]}{jd_hint}"
    return _call_deepseek(ENGLISH_RESUME_PROMPT, user_msg, temperature=0.3, max_tokens=4096)


COVER_LETTER_PROMPT = """你是一位求职信写作专家。根据简历和JD生成定制求职信。

返回JSON：
{
  "cover_letter": "完整的求职信...",
  "highlights": ["亮点提炼1", "亮点提炼2"],
  "tone": "专业热情/稳重/创新",
  "customization_tips": "针对此JD的调整建议"
}
"""


def generate_cover_letter(resume_text, jd_text):
    """根据简历和JD生成定制求职信"""
    if not DEEPSEEK_API_KEY:
        return {"error": "未配置AI API密钥"}
    user_msg = f"简历:\n{resume_text[:3000]}\n职位描述:\n{jd_text[:3000]}"
    return _call_deepseek(COVER_LETTER_PROMPT, user_msg, temperature=0.4, max_tokens=3072)
