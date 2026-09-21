# -*- coding: utf-8 -*-
"""
解析 面试题.docx -> 结构化题库 data/questions.json

文档结构（已通过 2246 段原文 + 结构树双重确认）：

    2026年7月5日                                        <- 日期分组（47 个）
    ==和equals的区别？两个都重写...？hashcode...？        <- 大题头（把当天几个子问题串成一行）
    ==和equals的区别？                                   <- 小节题  ← 真正要背的
    ==比较基本数据类型时比较值，比较引用数据类型时...      <- 答案要点
      补充：xxx                                        <- 补充（不计分）
      （1）xxx                                         <- 带序号补充（不计分）

核心判定规则（关键洞察）：
    「以 ？/? 结尾，且其下一非空行【不以 ？ 结尾】」的行 = 一道真正的小节题。
    大题头行虽然也以？结尾，但它下一行仍以？结尾，因此被自动排除。
    极少数题干不以问号结尾（如「说一下HashMap的底层原理」），用白名单补捞：
    仅当该行的下一行是"答案块"且该行本身无句末标点时才认定为题。
"""

import json
import re
import zipfile
from collections import Counter
from pathlib import Path

DOCX = Path(r"C:\Users\ekko\Desktop\面试题.docx")
OUT = Path(__file__).parent / "data" / "questions.json"

RE_DATE = re.compile(r"^20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日$")
RE_SUPP = re.compile(r"^补\s*充\s*[:：]")
RE_PARA_NUM = re.compile(r"^[（(]\s*\d+\s*[）)]")
RE_ENDS_Q = re.compile(r"[？?]\s*$")
# 句末标点：出现则基本可判为"答案句"而非"题干"
RE_SENT_END = re.compile(r"[。；;]\s*$")

# 不以问号结尾的题干，只认这些明确指令词开头（保守）
STEM_LEADS = (
    "说一下", "介绍一下", "谈谈", "讲讲", "聊聊", "说明一下",
    "什么是", "为什么要", "为什么", "有哪些", "怎么", "如何",
)

# 结构性噪音：这些行是排版小标题，既不是题也不是答案
NOISE_PREFIXES = ("从几个维度来对比", "从几个方面", "分成", "分两种情况", "几种思路",
                  "思路如下", "重点介绍", "注意这道题")

# 大题头长度阈值：超过这个字数的行，若后面紧跟另一道题（或分节标题），
# 则判定为「大题头」而非「要背的小节题」。
TOPIC_HEADER_MIN_LEN = 40


def is_topic_header(line: str, nxt: str) -> bool:
    """判定 line 是否为「大题头」——即把当天若干子问题串联起来的那一行。

    充分条件（满足任一即是）：
      1. 该行含 >= 2 个问号，且【以问号结尾】—— 明显是把多个问题堆在一行。
         例："什么是代理？静态代理和动态代理的区别是什么？jdk动态代理和cglib的区别是什么？"
         例："用下标循环，边循环并删除List的数据会有什么问题？有哪些方案可以解决？"
      2. 该行以问号结尾、较长、且下一行也是问句结尾 ——
         说明它是个"总起问句"，其下的子问句才是真正要背的。
         例："上一家公司的薪资是多少？你的期望薪资是多少？暂时我们给不到…你还考虑吗？"

    必要条件（两个条件都要求）：【本行必须以问号结尾】。
    这一条很关键：像 "就是上一家公司和当前找的公司是异地的，比如：…
    这种情况回答已离职…" 这种句子，虽然正文里引用了带问号的原话（"为什么不先找到工作
    再离职？"），但它本身是【陈述句答案】，不能误判成大题头。
    """
    if not RE_ENDS_Q.search(line):
        return False
    if line.count("？") + line.count("?") >= 2:
        return True
    if len(line) >= TOPIC_HEADER_MIN_LEN and RE_ENDS_Q.search(nxt):
        return True
    return False


# ---------------------------------------------------------------- 文本抽取

def extract_paragraphs(docx_path: Path) -> list[str]:
    with zipfile.ZipFile(docx_path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    raw = re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", xml, re.S)
    out: list[str] = []
    for p in raw:
        p = re.sub(r"<w:br\s*/>", "\n", p)
        p = re.sub(r"<w:tab\s*/>", "\t", p)
        t = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S))
        t = (t.replace("&lt;", "<").replace("&gt;", ">")
              .replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&"))
        out.append(t.replace("\u3000", " ").strip())
    return out


# ------------------------------------------------------- 分类标签

CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    # 软技能优先（避免"锁"等词把 HR 题误分）
    ("软技能/HR", (
        "离职", "上家公司", "上家", "期望薪资", "薪资", "加班", "优点", "缺点",
        "职业规划", "你想问", "想问我们", "最快什么时候可以入职", "为什么选择",
        "自我介绍", "换工作", "offer", "工作氛围", "有什么要求", "怎么学习",
        "学一个新技术", "贵公司", "评价一下", "你通常", "你觉得你", "你未来",
        "你的简历", "你还有什么", "谈谈你", "说说你", "面了多久",
    )),
    ("并发/JUC", (
        "线程", "并发", "synchronized", "volatile", "aqs", "cas", "juc",
        "threadlocal", "concurrenthashmap", "countdownlatch", "semaphore",
        "cyclicbarrier", "reentrantlock", "原子", "可见性", "有序性", "死锁",
        "线程池", "threadpoolexecutor", "阻塞队列", "completablefuture",
        "指令重排序", "内存屏障", "自旋", "cas+", "读写锁",
    )),
    ("JVM", (
        "jvm", "垃圾回收", "垃圾收集", "gc", "内存模型", "内存结构", "内存区域",
        "堆", "方法区", "元空间", "类加载", "双亲委派", "oom", "内存泄漏",
        "内存溢出", "逃逸分析", "可达性", "引用计数", "cms", "g1", "fullgc",
        "younggc", "stw", "调优", "jvm调优", "对象创建", "对象头",
    )),
    ("Spring", (
        "spring", "ioc", "aop", "bean", "依赖注入", "事务", "transactional",
        "循环依赖", "三级缓存", "springmvc", "springboot", "springcloud",
        "自动装配", "starter", "拦截器", "过滤器", "监听器", "生命周期",
        "scope", "注解", "动态代理",
    )),
    ("MySQL/数据库", (
        "mysql", "索引", "sql", "事务隔离", "mvcc", "explain", "慢查询", "主从",
        "分库分表", "binlog", "redolog", "undolog", "回表", "覆盖索引",
        "聚簇索引", "b+树", "b+ 树", "数据库", "范式", "join", "存储引擎",
        "innodb", "myisam", "间隙锁", "表锁", "行锁", "幻读", "脏读", "不可重复读",
    )),
    ("Redis/缓存", (
        "redis", "缓存", "穿透", "雪崩", "击穿", "分布式锁", "持久化", "rdb", "aof",
        "过期", "淘汰", "lru", "lfu", "哨兵", "主从复制", "memcached", "caffeine",
        "ehcache", "guavacache", "热key", "大key",
    )),
    ("MQ/消息队列", (
        "mq", "rabbitmq", "kafka", "rocketmq", "消息队列", "交换机", "消费者",
        "生产者", "幂等", "消息丢失", "消息重复", "延迟队列", "死信", "消息可靠性",
    )),
    ("微服务/分布式", (
        "微服务", "分布式", "注册中心", "nacos", "eureka", "feign", "gateway",
        "网关", "负载均衡", "熔断", "降级", "限流", "sentinel", "seata",
        "分布式事务", "链路追踪", "dubbo", "rpc", "tcc", "saga", "2pc", "cap",
        "base", "一致性", "集群",
    )),
    ("集合", (
        "hashmap", "arraylist", "linkedlist", "hashset", "list", "set", "map",
        "collection", "treeset", "treemap", "linkedhashmap", "vector",
        "copyonwritearraylist", "数组", "集合", "迭代器", "iterator", "扩容",
        "红黑树", "哈希冲突", "hash冲突", "拉链法", "hashcode",
    )),
    ("MyBatis/ORM", (
        "mybatis", "mybatisplus", "orm", "mapper", "一级缓存", "二级缓存",
        "动态sql", "延迟加载", "分页插件",
    )),
    ("设计模式", (
        "设计模式", "单例", "工厂模式", "策略模式", "模板方法", "观察者",
        "责任链", "建造者", "适配器", "装饰器", "代理模式",
    )),
    ("计算机网络/OS", (
        "http", "https", "tcp", "udp", "三次握手", "四次挥手", "osi", "网络",
        "cookie", "session", "jwt", "token", "跨域", "dns", "操作系统",
        "进程", "linux", "磁盘", "cpu", "io模型", "bio", "nio", "aio", "零拷贝",
    )),
    ("工程/中间件", (
        "nginx", "docker", "k8s", "kubernetes", "git", "maven", "jenkins",
        "elasticsearch", "mongodb", "部署", "日志", "监控",
    )),
    ("Java基础", (
        "string", "stringbuilder", "stringbuffer", "equals", "==", "final",
        "abstract", "接口", "抽象类", "重写", "重载", "多态", "封装", "继承",
        "泛型", "异常", "反射", "代理", "序列化", "包装类", "integer",
        "面向对象", "lambda", "stream", "optional", "object", "内部类", "枚举",
        "基本类型", "jdk", "新特性", "不可变", "值传递", "引用传递", "static",
    )),
]


def classify(text: str) -> str:
    low = text.lower()
    best, best_score = "其他", 0
    for cat, kws in CATEGORY_RULES:
        score = sum((2 if len(kw) >= 3 else 1) for kw in kws if kw in low)
        if score > best_score:
            best, best_score = cat, score
    return best


# ---------------------------------------------------------------- 主解析

def is_question_line(seg: list[str], i: int) -> bool:
    """判定 seg[i] 是否为一道「要背的小节题」。

    判定依据（按优先级）：

    A. 大题头排除
       大题头 = 很长的一行，且其下一行仍是「题」或「分节标题」。
       例："什么是代理？静态代理和动态代理的区别是什么？jdk动态代理和cglib的区别是什么？"
           下一行 "什么是代理？" → 长行是大题头，不是本节题。

    B. 主规则：以 ？/? 结尾，且下一行【不是】以？结尾的题行 → 是本节题。
       例："说一下HashMap的底层原理" 下一行 "从几个方面来介绍" → 是题。

    C. 补捞：不以问号结尾，但在指令词白名单里，且下一行是答案块 → 是本节题。
    """
    s = seg[i]
    if not s or RE_SUPP.match(s) or RE_PARA_NUM.match(s) or RE_DATE.match(s):
        return False
    if any(s.startswith(p) for p in NOISE_PREFIXES):
        return False

    nxt = seg[i + 1] if i + 1 < len(seg) else ""
    nxt_is_q = bool(RE_ENDS_Q.search(nxt))
    nxt_is_section = any(nxt.startswith(p) for p in NOISE_PREFIXES)

    # ---- A. 大题头排除 ----
    if is_topic_header(s, nxt):
        return False

    # ---- B. 前导分节标题：下一行是「从几个维度来对比」这类引导语 ----
    # 说明当前行是这一组要点的标题（题眼本身），不是要背的小节题。
    # 例：「String、StringBuilder和StringBuffer的区别」+「从几个维度来对比」
    if nxt_is_section:
        if not RE_SENT_END.search(s) and not RE_SUPP.match(s):
            return True

    # ---- C. 主规则 ----
    if RE_ENDS_Q.search(s):
        if nxt_is_q:
            return False          # 下一行还是问句 → 当前是"上行"而非小节题
        return True

    # ---- D. 补捞：无问号的题干（"说一下HashMap的底层原理"）----
    if any(s.startswith(lead) for lead in STEM_LEADS):
        if nxt and not nxt_is_q and not RE_SUPP.match(nxt):
            if not RE_SENT_END.search(s):     # 题干本身不该是带句号的完整句子
                return True
    return False


def parse(lines: list[str]) -> tuple[list[dict], list[dict]]:
    date_idx = [i for i, l in enumerate(lines) if RE_DATE.match(l)]
    blocks: list[tuple[str, list[str]]] = []
    if not date_idx:
        blocks.append(("未知日期", lines))
    else:
        if date_idx[0] > 0:
            blocks.append(("未知日期", lines[: date_idx[0]]))
        for a, b in zip(date_idx, date_idx[1:]):
            blocks.append((lines[a], lines[a + 1: b]))
        blocks.append((lines[date_idx[-1]], lines[date_idx[-1] + 1:]))

    questions: list[dict] = []
    warnings: list[dict] = []

    for date, seg_raw in blocks:
        seg = [l for l in seg_raw if l]
        if not seg:
            continue

        q_pos = [i for i in range(len(seg)) if is_question_line(seg, i)]

        # 补漏：若某个「大题头」后面【没有任何】被识别出的子问题，
        # 说明它其实是一道独立的题（只是正文里引用了带问号的原话）。
        # 这种情况下把它自己也作为一道题收入。
        for i in range(len(seg)):
            if any(seg[i].startswith(p) for p in NOISE_PREFIXES):
                continue
            nxt = seg[i + 1] if i + 1 < len(seg) else ""
            if not is_topic_header(seg[i], nxt):
                continue
            has_sub = any(i < p for p in q_pos)
            if not has_sub:
                q_pos.append(i)
        q_pos.sort()

        if not q_pos:
            warnings.append({"date": date, "reason": "no_question", "lines": len(seg)})
            continue

        for k, pos in enumerate(q_pos):
            end = q_pos[k + 1] if k + 1 < len(q_pos) else len(seg)
            body = seg[pos + 1: end]

            core, extra = [], []
            for j in range(pos + 1, end):
                line = seg[j]
                # 跳过大题头：它是"下一组子问题"的串联标题，不属于本题答案。
                nxt = seg[j + 1] if j + 1 < len(seg) else ""
                if is_topic_header(line, nxt):
                    continue
                if RE_SUPP.match(line) or RE_PARA_NUM.match(line):
                    extra.append(line)
                elif any(line.startswith(p) for p in NOISE_PREFIXES):
                    extra.append(line)     # "从几个维度来对比" 归入补充提示
                else:
                    core.append(line)

            if not core:
                warnings.append({"date": date, "q": seg[pos][:40],
                                 "reason": "no_core_points"})
                continue

            qtext = seg[pos]
            cat = classify(qtext + " " + " ".join(core[:4]))

            questions.append({
                "id": None,
                "date": date,
                "question": qtext,
                "core_points": core,
                "extra_points": extra,
                "category": cat,
                "_raw_cat": cat,
            })

    # ---- 分类继承：自身判为"其他"的题，继承同一日期分组内上一道题的分类 ----
    # 因为文档里存在大量追问（"怎么解决？""一般是什么原因导致的？"），
    # 它们本身没有技术关键词，语义上属于前一道题。
    last_cat_by_date: dict[str, str] = {}
    for q in questions:
        if q["category"] == "其他":
            inherit = last_cat_by_date.get(q["date"])
            if inherit and inherit != "其他":
                q["category"] = inherit
                q["category_inherited"] = True
        else:
            last_cat_by_date[q["date"]] = q["category"]

    for i, q in enumerate(questions, 1):
        q["id"] = f"q{i:04d}"
        q.pop("_raw_cat", None)
        # core_points 过长时按中文标点切成"要点"（AI 打分粒度更细）
        q["rubric"] = build_rubric(q["core_points"])
    return questions, warnings


def build_rubric(core_points: list[str]) -> list[str]:
    """把答案原文整理成「打分点」列表。

    文档里的答案有两种形态：
      (a) 短标签 + 内容  →  "可变性" / "String底层是用final修饰…"
      (b) 直接就是完整句子 → "重写是当子类提供了…"

    对 (a)，绝不能把"可变性"单独列为一条打分点——它只是个分节标题，
    单独计分会让总分被虚高的要点数稀释，也会让 AI 误以为要背这个词。
    因此规则是：
      1. 短标签（<= 12 字、不含标点、不以句号结尾）→ 作为前缀拼到下一个内容点上；
      2. 其余按句号/分号切分，合并过短碎片；
      3. 丢弃无法归属的孤立短标签。
    """
    # 先按"最小单元"展开（长句切句）
    units: list[str] = []
    for p in core_points:
        p = p.strip()
        if not p:
            continue
        if len(p) <= 80:
            units.append(p)
            continue
        buf = ""
        for s in re.split(r"(?<=[。；;])", p):
            s = s.strip()
            if not s:
                continue
            if len(buf) + len(s) <= 80:
                buf += s
            else:
                if buf:
                    units.append(buf)
                buf = s
        if buf:
            units.append(buf)

    def is_label(u: str) -> bool:
        """是否是分节小标题（"可变性"、"线程安全"、"底层数据结构"）。"""
        return len(u) <= 12 and not re.search(r"[。，、；：,;]", u)

    out: list[str] = []
    pending: str | None = None
    for u in units:
        if is_label(u):
            if pending:
                # 连着两个标签，前一个没有内容承接 → 丢弃前一个
                pending = u
            else:
                pending = u
            continue
        if pending:
            out.append(f"{pending}：{u}")
            pending = None
        else:
            out.append(u)
    # pending 未被消费说明是末尾孤立标签，丢弃
    return out


def main() -> None:
    lines = extract_paragraphs(DOCX)
    questions, warnings = parse(lines)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(questions, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"段落总数      : {len(lines)}")
    print(f"解析出题目    : {len(questions)}")
    print(f"警告          : {len(warnings)}")
    print(f"平均要点数    : {sum(len(q['core_points']) for q in questions)/len(questions):.1f}")

    print("\n分类分布:")
    for c, n in Counter(q["category"] for q in questions).most_common():
        print(f"  {c:<18} {n:>4}")

    print("\n--- 抽样（前5 + 中5） ---")
    mid = len(questions) // 2
    for q in questions[:5] + questions[mid: mid + 5]:
        print(f"\n[{q['id']}] {q['date']} · {q['category']}")
        print(f"  Q: {q['question'][:78]}")
        for p in q["core_points"][:2]:
            print(f"     - {p[:72]}")

    if warnings:
        print(f"\n--- 警告明细（前8 / 共{len(warnings)}） ---")
        for w in warnings[:8]:
            print(" ", w)


if __name__ == "__main__":
    main()
