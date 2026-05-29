import re
import os

# 规则标签：基于项目文件夹名
RULE_BY_PROJECT = {
    "audit-report-review": "审计复核",
    "contract-approval-auditing": "合同审核",
    "contract-approval": "合同审核",
    "contract-sentinel": "合同审核",
    "gdjl-report": "财报分析",
    "finance-review": "财报分析",
    "financial-report-review": "财报分析",
    "share-based-payment": "股权激励",
    "tax-report-generator": "税务申报",
    "consolidated-audit-report": "审计复核",
    "auto-collect-inquiry": "自动化",
    "lease": "租赁准则",
    "租赁制度": "租赁准则",
    "exam": "考试",
    "brainstorming": "方案设计",
    "writing-plans": "实施计划",
    "humanizer": "文本润色",
    "humanizer-zh": "文本润色",
    "wechat": "微信",
    "wechat-cli": "微信",
    "weibo": "微博",
    "ocr": "OCR识别",
    "OCR": "OCR识别",
    "dev": "技术开发",
    "深色模式": "技术开发",
    "关屏小工具": "技术开发",
    "codex-launcher": "技术配置",
    "cc-bypassmode": "技术配置",
    "cc-switch": "技术配置",
    "claude-desktop-api-switcher": "技术配置",
    "DeepSeek": "技术配置",
    "mcp": "技术配置",
    "MCP": "技术配置",
    "图片整理": "自动化",
    "organization": "自动化",
    "bookmarks": "整理",
    "C盘清理": "系统维护",
    "cleanup": "系统维护",
    "独立": "独立审计",
    "Independent": "独立审计",
    "Investment": "投资分析",
    "Investment2": "投资分析",
    "Investment3": "投资分析",
    "investment_system": "投资分析",
    "年报复核": "审计复核",
    "报表": "财报分析",
    "Scrapling": "爬虫",
    "downloads": "下载管理",
    "wechat-article": "公众号",
    "distill": "技能提炼",
    "skills-archive": "技能提炼",
    "Python": "技术开发",
    "PPT": "PPT制作",
    "CV": "简历",
    "review": "代码审查",
    "moni": "模拟组合",
    "mobile": "移动端",
    "conversation": "会话管理",
    "sync": "同步配置",
    "webdav": "同步配置",
}

# 基于内容关键词的规则标签
CONTENT_KEYWORDS = [
    (r"租赁|使用权资产|租约|承租|出租|租赁负债", "租赁准则"),
    (r"股份支付|股权激励|期权|限制性股票|行权", "股权激励"),
    (r"所得税|递延所得税|税务|纳税|税率|增值税|企业所得税", "税务申报"),
    (r"合同|签约|付款|合同审核|供应商|中标|招投标|采购|验收", "合同审核"),
    (r"审计|复核|审查|财报|报表|附注|勾稽|审定|期初|期末|底稿", "审计复核"),
    (r"OCR|识别|图片|扫描|pdf转|文字提取|tesseract", "OCR识别"),
    (r"Excel|表格|公式|vlookup|透视表|xlsx|xls|单元格", "Excel"),
    (r"Python|脚本|自动化|批量|爬虫|crawl|scrape", "自动化"),
    (r"MCP|server|配置|settings|json|协议|tool|resource", "技术配置"),
    (r"CLAUDE\.md|skill|提示词|prompt|agent|心智模型", "Skill开发"),
    (r"\bPE\b|\bPB\b|估值|收益率|分红|股票|基金仓位|投资组合", "投资分析"),
    (r"考试|备考|复习|考题|题库|学习|课程", "考试"),
    (r"微信|公众号|文章|抓取|爬取|mp\.weixin", "微信"),
    (r"润色|改写|去AI|自然|人类|humanizer", "文本润色"),
    (r"PPT|演示|幻灯片|展示|presentation", "PPT制作"),
    (r"简历|面试|求职|CV", "简历"),
    (r"独立审计|职业怀疑|四大|会计师事务所", "独立审计"),
    (r"方案设计|设计文档|brainstorming|原型|设计", "方案设计"),
]

# AI标记词库（按专业领域分组）
AI_TERM_WEIGHTS = {
    "审计": 3, "复核": 3, "勾稽": 5, "审计调整": 4, "审计程序": 3,
    "财报": 3, "报表": 2, "资产负债表": 3, "利润表": 3, "现金流量表": 3,
    "附注": 3, "合并报表": 4, "抵消分录": 5,
    "租赁": 4, "使用权资产": 4, "租赁负债": 5, "租约": 4,
    "合同": 3, "付款": 3, "供应商": 3, "中标": 3, "招投标": 4,
    "股权": 4, "股份支付": 5, "期权": 4, "限制性股票": 5,
    "税务": 3, "所得税": 4, "递延": 4, "税率": 3,
    "Excel": 3, "表格": 2, "公式": 2, "数据透视": 4,
    "Python": 4, "脚本": 3, "自动化": 3, "批量": 3,
    "MCP": 4, "skill": 3, "CLAUDE.md": 4, "settings": 2,
    "OCR": 5, "识别": 3, "扫描": 2, "PDF": 3,
    "关键词": 2, "搜索": 2, "查询": 2,
    "股票": 4, "基金": 4, "估值": 4, "投资分析": 5, "投资回报": 4, "ROI": 4,
    "方案": 2, "设计": 3, "原型": 3,
    "考试": 4, "备考": 4, "学习": 2,
    "微信": 3, "公众号": 4, "文章": 2,
    "润色": 4, "改写": 3, "自然": 2,
    "PPT": 3, "简历": 4, "面试": 3,
}


def _project_matches(proj_lower, rules):
    """精确匹配项目名（不包含路径中的BaiduSyncdisk等通用片段）。"""
    matches = []
    for key, label in rules.items():
        # 用单词边界匹配或完整匹配，避免"sync"匹配到"BaiduSyncdisk"
        if key in proj_lower.split("-") or key in proj_lower.replace("--", "-").split("-"):
            matches.append((label, "rule"))
            continue
        # 也支持 _ 分隔
        if key in proj_lower.split("_"):
            matches.append((label, "rule"))
    # 去重保留顺序
    seen = set()
    result = []
    for label, source in matches:
        if label not in seen:
            seen.add(label)
            result.append((label, source))
    return result


def apply_rule_topics(session_data):
    """基于项目名和内容关键词打规则标签。"""
    topics = []
    project = session_data.get("project", "") or ""
    proj_lower = project.lower()

    # 项目名映射（精确片段匹配）
    topics.extend(_project_matches(proj_lower, RULE_BY_PROJECT))

    # 内容关键词匹配
    first_content = (session_data.get("first_user_content") or "") + " " + (session_data.get("summary") or "")
    for pattern, label in CONTENT_KEYWORDS:
        if re.search(pattern, first_content, re.IGNORECASE):
            if label not in [t[0] for t in topics]:
                topics.append((label, "rule"))

    return topics


def apply_ai_topics(session_data):
    """基于会话内容的关键词频率统计打 AI 标签。"""
    text = session_data.get("first_user_content") or ""
    text += " " + (session_data.get("summary") or "")

    # 统计术语频率
    scores = {}
    for term, weight in AI_TERM_WEIGHTS.items():
        count = len(re.findall(re.escape(term), text, re.IGNORECASE))
        if count > 0:
            scores[term] = count * weight

    if not scores:
        return []

    # 按权重分组到领域
    domain_scores = {}
    domain_map = {
        "审计复核": {"审计", "复核", "勾稽", "审计调整", "审计程序", "附注", "合并报表", "抵消分录"},
        "财报分析": {"财报", "报表", "资产负债表", "利润表", "现金流量表"},
        "租赁准则": {"租赁", "使用权资产", "租赁负债", "租约"},
        "合同审核": {"合同", "付款", "供应商", "中标", "招投标"},
        "股权激励": {"股权", "股份支付", "期权", "限制性股票"},
        "税务申报": {"税务", "所得税", "递延", "税率"},
        "Excel": {"Excel", "表格", "公式", "数据透视"},
        "自动化": {"Python", "脚本", "自动化", "批量"},
        "技术配置": {"MCP", "skill", "CLAUDE.md", "settings"},
        "OCR识别": {"OCR", "识别", "扫描", "PDF"},
        "投资分析": {"股票", "基金", "估值", "投资回报", "ROI", "收益率", "分红"},
        "方案设计": {"方案", "设计", "原型"},
        "考试": {"考试", "备考", "学习"},
        "微信": {"微信", "公众号", "文章"},
        "文本润色": {"润色", "改写", "自然"},
        "PPT制作": {"PPT"},
    }

    for domain, terms in domain_map.items():
        score = sum(scores.get(t, 0) for t in terms)
        if score > 0:
            domain_scores[domain] = score

    # 取得分最高的 1-3 个标签
    sorted_domains = sorted(domain_scores.items(), key=lambda x: -x[1])
    return [(d, "ai") for d, s in sorted_domains[:3]]


def apply_all_topics(session_data):
    """先规则后AI，返回去重后的标签列表。"""
    seen = set()
    result = []
    for topic, source in apply_rule_topics(session_data) + apply_ai_topics(session_data):
        if topic not in seen:
            seen.add(topic)
            result.append((topic, source))
    return result
