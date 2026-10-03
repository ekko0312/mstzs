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

# 源文档可能被挪过位置（比如放进了"简历"文件夹），这里按优先级自动找。
DOCX_CANDIDATES = (
    Path(r"C:\Users\ekko\Desktop\面试题.docx"),
    Path(r"C:\Users\ekko\Desktop\简历\面试题.docx"),
    Path(__file__).parent / "面试题.docx",
)
DOCX = DOCX_CANDIDATES[0]          # 兼容老引用；实际以 resolve_docx() 为准
OUT = Path(__file__).parent / "questions.json"


def resolve_docx() -> Path:
    """按候选列表找到源文档 面试题.docx。"""
    for p in DOCX_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError(
        "找不到源文档 面试题.docx，请放到以下任一位置：\n  "
        + "\n  ".join(str(p) for p in DOCX_CANDIDATES)
    )

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


def is_lead_header(seg: list[str], i: int) -> bool:
    """判定 seg[i] 是否为「承接口」——被主规则排除的上级问句。

    文档里有一条很常见的写法：先写一个总起问句，紧接着逐条展开。

        为什么选择b+树，而不是二叉树、平衡二叉树、红黑树、b树？   <- 本函数认这个
        为什么不是二叉树？
        当极端情况下……退化为链表……O(n)
        为什么不选择平衡二叉树？
        ……

    总起句自身以？结尾，但按 is_question_line 的规则 C（下一行还是问句，
    说明它是"上行"而非本节题）会被排除掉，于是它既不是题、也没进答案，
    直接凭空消失。

    消失的后果就是这一串子问题全部失去前因——用户看到孤零零一句
    「为什么不选择二叉树？」，根本不知道在跟什么比，没法回答。
    所以这里把它单独捞出来，挂在后续子问题上，作为「承接上文」。
    """
    s = seg[i]
    if not s or RE_SUPP.match(s) or RE_PARA_NUM.match(s) or RE_DATE.match(s):
        return False
    if any(s.startswith(p) for p in NOISE_PREFIXES):
        return False
    if not RE_ENDS_Q.search(s):
        return False
    nxt = seg[i + 1] if i + 1 < len(seg) else ""
    return bool(RE_ENDS_Q.search(nxt))


def _scan_context_headers(seg: list[str], q_pos: list[int]) -> list[tuple[int, str, str]]:
    """扫出全部题干链的头，返回 [(下标, 类型, 原文)]，类型 ∈ {"topic","lead"}。

    topic —— 大题头，把当天若干子问题串成一行的总起句；
    lead  —— 承接口，被规则 C 排除的上级问句。
    q_pos 里的下标最终会成题，不算头（否则会和题目自身重复）。
    """
    qset = set(q_pos)
    out: list[tuple[int, str, str]] = []
    for i, s in enumerate(seg):
        if i in qset or not s:
            continue
        if RE_SUPP.match(s) or RE_PARA_NUM.match(s):
            continue
        nxt = seg[i + 1] if i + 1 < len(seg) else ""
        if is_topic_header(s, nxt):
            out.append((i, "topic", s))
        elif is_lead_header(seg, i):
            out.append((i, "lead", s))
    return out


# 追问型题干的开口词。
# 这类题脱离上下文就没法答：看到孤零零一句「为什么不选择二叉树？」，
# 谁也不知道是在跟什么比。它们必须挂上前因才成立。
FOLLOWUP_LEADS = (
    "为什么", "那", "那么", "所以", "怎么", "如何", "还有", "然后", "接着",
    "它", "这个", "这种", "这里", "如果", "说一下为什么", "说一下为什么是",
    "为啥", "凭什么", "具体",
)


def _is_followup(qtext: str) -> bool:
    return any(qtext.startswith(p) for p in FOLLOWUP_LEADS)


def build_context(seg: list[str], q_pos: list[int]) -> list[dict]:
    """为每道题算出它的上下文，顺序与 q_pos 一一对应。

    topic = 最近一次出现的「大题头」，代表这一整组问题的主题链；
    lead  = 最近一次出现的「承接口」，代表这组题的直接前因。

    每遇到一个新的大题头，lead 会清空——新话题不该继承上一个话题的前因。
    lead 还只对【紧随其后的连续追问】有效：一旦出现一道能独立成立的题
    （比如"要你学一个新技术，你要多久？"），说明这条追问链已经走完，
    前因要立刻失效，否则会一路串到隔壁话题的题目上去。
    """
    headers = _scan_context_headers(seg, q_pos)
    out: list[dict] = []
    topic = lead = None
    hi = 0
    for pos in q_pos:
        while hi < len(headers) and headers[hi][0] < pos:
            _, kind, text = headers[hi]
            if kind == "topic":
                topic, lead = text, None
            else:                       # 新的承接口覆盖旧的
                # 同一天的笔记可能连续记录多个话题。新的总起问句若不属于
                # 旧大题头，不能继续显示旧话题（HashMap 树型选择就是一例）。
                if topic and text not in topic:
                    topic = None
                lead = text
            hi += 1

        qtext = seg[pos]
        use_lead = lead
        if use_lead and not _is_followup(qtext):
            lead = None                 # 追问链到此为止
            use_lead = None

        # 大题头只覆盖其中列出的子问题。下一道独立题不能继续带着旧话题，
        # 尤其不能让 HR 题继承前一道技术题的背景。
        if topic and qtext not in topic and not use_lead:
            topic = None

        ctx: dict[str, str] = {}
        if topic and topic != qtext:
            ctx["topic"] = topic
        if use_lead and use_lead != qtext and use_lead != topic:
            ctx["lead"] = use_lead
        out.append(ctx)
    return out


# 源笔记里的短问句有些在随机抽题时无法单独理解。这里按稳定题号和原题
# 双重校验进行人工澄清；第三、四项分别是答题场景和回答方向，不写结论。
# 重跑解析时也会保留这些澄清，不会被原始 docx 覆盖。
QUESTION_CLARIFICATIONS: dict[str, tuple[str, str, str, str]] = {
    "q0014": ("有哪些方案可以解决？", "遍历 List 时同时删除元素，应该怎么处理？", "讨论按下标遍历并删除 List 元素的场景。", "说明遍历顺序和安全删除的可选方式。"),
    "q0032": ("什么时候链表会转成红黑树？", "HashMap 的桶中，链表什么时候会转成红黑树？", "HashMap 的哈希冲突会让同一个桶里出现链表。", "说明链表长度、数组容量与树化条件的关系。"),
    "q0033": ("什么时候红黑树会转成链表？", "HashMap 的桶中，红黑树什么时候会转回链表？", "讨论 HashMap 桶内节点数量减少后的结构变化。", "说明退化条件，并与树化阈值区分。"),
    "q0034": ("说一下为什么是8？", "HashMap 的链表树化阈值为什么是 8？", "讨论 HashMap 桶内链表转红黑树的阈值。", "从冲突概率和维护树的成本解释这个取舍。"),
    "q0035": ("说一下为什么是6？", "HashMap 的红黑树退化阈值为什么是 6？", "讨论 HashMap 桶内红黑树转回链表的阈值。", "解释与树化阈值留出间隔的目的。"),
    "q0036": ("为什么不选择二叉树？", "HashMap 链表树化时，为什么不使用普通二叉搜索树？", "HashMap 的桶需要在内存中处理哈希冲突。", "比较极端插入顺序下的树高和查找效率。"),
    "q0037": ("为什么不选择平衡二叉树？", "HashMap 链表树化时，为什么不使用严格平衡的二叉树？", "HashMap 的桶需要兼顾查找和频繁增删。", "比较严格平衡与红黑树的调整成本。"),
    "q0038": ("为什么不选择B+树？", "HashMap 链表树化时，为什么不使用 B+ 树？", "HashMap 的桶内节点主要在内存中查找和更新。", "比较 B+ 树面向磁盘页的设计与内存桶的需求。"),
    "q0044": ("key为什么不可以为null？", "ConcurrentHashMap 为什么不允许 null key？", "讨论 ConcurrentHashMap 的键约束。", "从并发容器的语义与实现取舍解释，别与 HashMap 混淆。"),
    "q0045": ("value为什么不可以为null？", "ConcurrentHashMap 为什么不允许 null value？", "讨论并发读取 ConcurrentHashMap 时返回 null 的含义。", "解释键不存在与值为空如何产生歧义。"),
    "q0046": ("key为什么不可以为null？", "Hashtable 为什么不允许 null key？", "讨论 Hashtable 的键约束，与上一题的 ConcurrentHashMap 区分。", "结合 Hashtable 的实现和 API 设计解释。"),
    "q0047": ("value为什么不可以为null？", "Hashtable 为什么不允许 null value？", "讨论 Hashtable 的值约束。", "结合 get 返回值的含义解释。"),
    "q0059": ("怎么解决？", "JDK 1.7 HashMap 并发扩容的头插法问题，怎么避免？", "多个线程同时扩容 HashMap 时，头插法可能引出问题。", "区分后续实现变化与真正的线程安全用法。"),
    "q0102": ("可逆吗？", "synchronized 的锁升级可以逆转吗？", "接着上一题的 synchronized 锁升级过程。", "说明锁状态变化是否会在运行过程中回退。"),
    "q0104": ("在mysql中有哪些实现？", "MySQL 中如何实现悲观锁和乐观锁？", "比较悲观锁和乐观锁在 MySQL 中的做法。", "分别给出一种实现思路及适用方式。"),
    "q0105": ("在java中有哪些实现？", "Java 中如何实现悲观锁和乐观锁？", "比较悲观锁和乐观锁在 Java 中的做法。", "分别举出常见机制或类。"),
    "q0107": ("怎么解决？", "CAS 的 ABA 问题怎么解决？", "接着乐观锁与 CAS 的 ABA 问题。", "解释如何识别值经历过变化。"),
    "q0110": ("行锁锁的是什么？", "InnoDB 的行锁实际锁住了什么？", "讨论 MySQL InnoDB 的行级锁。", "结合索引记录说明锁定对象。"),
    "q0111": ("增删改分别上什么锁？", "InnoDB 执行 INSERT、UPDATE、DELETE 时分别会涉及什么锁？", "讨论 MySQL InnoDB 的写操作。", "区分插入与按条件更新、删除，并说明索引条件的影响。"),
    "q0133": ("如何防篡改？", "JWT 如何防止载荷被篡改？", "讨论客户端携带 JWT、服务端验证令牌的过程。", "说明签名的生成与校验。"),
    "q0136": ("一般是什么原因导致的？", "项目需求延期通常由哪些原因导致？", "面试官在追问你经历过的需求延期。", "结合真实项目说明原因，区分可控和外部因素。"),
    "q0137": ("一般怎么处理？", "项目需求延期时，你通常怎么处理？", "面试官在追问你经历过的需求延期。", "说明评估、沟通、调整与后续复盘。"),
    "q0142": ("有哪些方式？", "Spring 依赖注入有哪些方式？", "接着 Spring 的 IoC 与依赖注入。", "按注入入口列举，并说明使用条件。"),
    "q0143": ("推荐用哪种？", "Spring 依赖注入推荐用哪种方式？为什么？", "在几种 Spring 依赖注入方式之间作选择。", "比较测试便利性、依赖完整性和项目约束。"),
    "q0156": ("怎么修改为多例？", "Spring Bean 怎么改成多例作用域？", "讨论 Spring Bean 的作用域配置。", "指出配置方式以及获取实例时的效果。"),
    "q0158": ("怎么变成懒加载？", "Spring Bean 怎么配置为懒加载？", "讨论 Spring Bean 的初始化时机。", "说明配置入口与首次创建时机。"),
    "q0167": ("怎么解决？", "Spring Bean 循环依赖怎么解决？", "两个 Bean 在创建时互相依赖。", "区分容器能处理的情况和需要调整设计的情况。"),
    "q0172": ("怎么解决？", "Spring 同一个 Bean 内部自调用导致代理失效，怎么解决？", "同一个 Bean 的方法互相调用，事务或 AOP 增强没有生效。", "说明如何让调用经过代理对象。"),
    "q0190": ("为什么用这个？", "你们项目为什么选择当前的垃圾收集器？", "接着你们项目所用垃圾收集器的追问。", "结合堆大小、停顿目标和项目实际配置解释。"),
    "q0192": ("优点是什么？", "JVM 双亲委派机制有什么优点？", "接着 Java 类加载的双亲委派机制。", "从避免重复加载和保护核心类回答。"),
    "q0194": ("怎么做单元测试的？", "你们项目通常怎么做单元测试？", "接着你们项目是否做单元测试的追问。", "说明实际使用的工具、测试对象和执行方式。"),
    "q0214": ("分别解决了什么问题？", "四种事务隔离级别分别解决了哪些并发读问题？", "讨论数据库事务的隔离级别。", "逐级说明脏读、不可重复读与幻读。"),
    "q0231": ("为什么不是二叉树？", "MySQL 索引为什么不使用普通二叉搜索树？", "为 MySQL 索引选择磁盘上的树结构。", "说明树高在极端数据顺序下如何变化。"),
    "q0232": ("为什么不选择平衡二叉树？", "MySQL 索引为什么不使用严格平衡的二叉树？", "为 MySQL 索引选择磁盘上的树结构。", "比较树高、调整成本和磁盘访问。"),
    "q0233": ("为什么不选择红黑树？", "MySQL 索引为什么不使用红黑树？", "为 MySQL 索引选择磁盘上的树结构。", "比较节点扇出、树高和磁盘 I/O。"),
    "q0234": ("为什么不选择b树？", "MySQL 索引为什么更常用 B+ 树而不是 B 树？", "比较 MySQL 索引可选的多路搜索树。", "说明非叶子节点存储内容与查询、范围扫描的影响。"),
    "q0235": ("为什么选择b+树？（面试也经常问你详细介绍一下b+树的结构）", "MySQL 索引为什么选择 B+ 树？请描述它的结构。", "讨论 InnoDB 索引的页与树结构。", "按非叶子节点、叶子节点、树高和范围查询组织回答。"),
    "q0243": ("怎么优化回表？", "MySQL 索引查询发生回表时，怎么减少回表？", "二级索引查到主键后还要读取聚簇索引。", "从查询列与索引覆盖的关系回答。"),
    "q0249": ("为什么推荐使用数字，而不推荐使用字符串？", "MySQL 主键为什么更推荐数字而不是字符串？", "接着自增数字主键的选型问题。", "比较索引键占用空间与每页可容纳的记录数。"),
    "q0250": ("数字为什么要自增呢？", "MySQL 数字主键为什么通常建议自增？", "接着 InnoDB 主键与 B+ 树的插入顺序问题。", "比较顺序插入和随机插入对页分裂的影响。"),
    "q0251": ("怎么优化慢接口？", "项目接口响应很慢时，你怎么定位并优化？", "从实际项目的一条慢接口出发。", "先定位耗时环节，再按证据选择优化手段并验证结果。"),
    "q0261": ("怎么统计qps的？", "项目的平均和峰值 QPS 是怎么统计的？", "面试官在追问你说出的项目流量数据来源。", "说明采集位置、统计窗口与数据依据。"),
    "q0266": ("分别有哪些算法？", "对称加密和非对称加密各有哪些常见算法？", "接着对称与非对称加密的比较。", "各举常见算法，并对应其密钥使用方式。"),
    "q0272": ("怎么解决时钟回拨的问题？", "雪花算法生成 ID 时遇到时钟回拨，怎么处理？", "系统时钟回退可能影响分布式 ID 生成。", "先说明风险，再给出可执行的检测和处理策略。"),
    "q0294": ("说一下常用的api？", "Java Stream 常用的 API 有哪些？", "讨论 Java Stream 的常见操作。", "按筛选、映射、排序、聚合和收集举例。"),
    "q0298": ("在项目中一般用来做什么？", "ThreadLocal 在项目中一般用来做什么？", "讨论同一线程内传递上下文数据。", "结合项目中的实际信息和使用位置举例。"),
    "q0299": ("使用上要注意什么？", "使用 ThreadLocal 时要注意什么？", "讨论线程复用时 ThreadLocal 数据的生命周期。", "说明清理时机及遗漏的风险。"),
    "q0308": ("说一下看门狗机制", "Redisson 分布式锁的看门狗机制是什么？", "讨论持锁任务执行时间超过初始租期的情况。", "说明续期条件、检查时机与释放后的行为。"),
    "q0311": ("怎么保证数据库和缓存的一致性？", "项目中如何保持数据库与 Redis 缓存的数据一致？", "以你项目里真正缓存的一类业务数据为例。", "说明写入顺序、并发读写与失败后的兜底策略。"),
    "q0374": ("这个场景为什么选择at模式不选择其他模式？", "你的分布式事务场景为什么选择 Seata AT 模式？", "接着你前一题举出的跨服务业务流程。", "结合事务边界、提交可见性与失败回滚解释取舍。"),
}


# 分类器只看关键词，容易把夹在技术笔记中的 HR/行为题继承成技术分类。
# 这些题归入独立的非技术题库；反向修正两道被误判成 HR 的技术题。
# 题号沿用原题库，不能因分类调整而重新编号，否则会丢失复习进度。
NON_TECH_QUESTION_IDS = {
    "q0098", "q0108", "q0120", "q0127", "q0135", "q0136", "q0137",
    "q0138", "q0164", "q0169", "q0170", "q0175", "q0180", "q0198",
    "q0259", "q0291", "q0292",
}
TECH_CATEGORY_FIXES = {
    "q0315": "Redis/缓存",
    "q0321": "工程/中间件",
}

# 原文排版中有两行被误接到了上一题的答案里，展示和评分都不应包含它们。
MISPLACED_ANSWER_LINES = {
    "q0054": "扩容一次，8+3=11，小于8的1.5倍也就是12，按12来算，最终list1数组长度为12",
    "q0341": "什么是tool calling？说一下tool calling的流程",
}


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

        # 每道题的上下文（大题头 / 直接承接口），与 q_pos 一一对应
        contexts = build_context(seg, q_pos)

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
                # 跳过承接口：它是下一串追问的总起句（"为什么是6和8？"），
                # 是一句【问题】而不是答案。以前它被当成答案要点混进本题，
                # 于是 rubric 里出现一条"回答出这个问句"的奇葩打分点，
                # 题目还会因此被误分类（见 build_context）。
                if is_lead_header(seg, j):
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
                "context": contexts[k],
                "_raw_cat": cat,
            })

    # ---- 分类继承：自身判为"其他"的题，继承同一日期分组内上一道题的分类 ----
    # 因为文档里存在大量追问（"怎么解决？""一般是什么原因导致的？"），
    # 它们本身没有技术关键词，语义上属于前一道题。
    #
    # 挂了前因的追问（lead）也一样要继承，而且必须继承：
    # 「为什么不选择红黑树？」这句字面里只有"红黑树"，单看词会判成"集合"，
    # 可它其实是在问 MySQL 索引为什么不用红黑树。追问的归属应该跟着它所在的
    # 那条链走，而不是拿它自己那点词去猜。所以这类题不参与关键词定类。
    last_cat_by_date: dict[str, str] = {}
    for q in questions:
        is_followup = bool((q.get("context") or {}).get("lead"))
        if is_followup or q["category"] == "其他":
            inherit = last_cat_by_date.get(q["date"])
            if inherit and inherit != "其他":
                q["category"] = inherit
                q["category_inherited"] = True
        else:
            last_cat_by_date[q["date"]] = q["category"]

    for i, q in enumerate(questions, 1):
        q["id"] = f"q{i:04d}"
        q.pop("_raw_cat", None)
        misplaced = MISPLACED_ANSWER_LINES.get(q["id"])
        if misplaced:
            if misplaced not in q["core_points"]:
                raise ValueError(f"{q['id']} 答案原文发生变化，请核对串题规则")
            q["core_points"].remove(misplaced)
        # core_points 过长时按中文标点切成"要点"（AI 打分粒度更细）
        q["rubric"] = build_rubric(q["core_points"])
        clarification = QUESTION_CLARIFICATIONS.get(q["id"])
        if clarification:
            original, clear_question, scene, focus = clarification
            if q["question"] != original:
                raise ValueError(f"{q['id']} 原题发生变化，请核对澄清规则")
            q["question"] = clear_question
            q["context"] = {"scene": scene, "focus": focus}
        if q["id"] in NON_TECH_QUESTION_IDS:
            q["category"] = "软技能/HR"
        elif q["id"] in TECH_CATEGORY_FIXES:
            q["category"] = TECH_CATEGORY_FIXES[q["id"]]
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
    docx = resolve_docx()
    lines = extract_paragraphs(docx)
    questions, warnings = parse(lines)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(questions, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"源文档        : {docx}")
    print(f"段落总数      : {len(lines)}")
    print(f"解析出题目    : {len(questions)}")
    print(f"警告          : {len(warnings)}")
    print(f"平均要点数    : {sum(len(q['core_points']) for q in questions)/len(questions):.1f}")

    n_ctx = sum(1 for q in questions if q.get("context"))
    n_lead = sum(1 for q in questions if q.get("context", {}).get("lead"))
    print(f"带上下文      : {n_ctx}  (其中有直接承接口的 {n_lead})")
    print(f"输出          : {OUT}")

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
