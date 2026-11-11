#!/usr/bin/env python3
"""紫微斗數排盤與宮干飛化計算（只用標準函式庫）。

用法：
  ziwei.py chart   <命主.json> [--taichi 宮]            本命盤、宮干飛化、祿忌循環
  ziwei.py decade  <命主.json> <虛歲> [--taichi 宮]     該虛歲所在大限的十二宮
  ziwei.py year    <命主.json> <西元年> [--taichi 宮]   流年四層四化、疊宮、飛化、流月
  ziwei.py convert [太極宮] [被查詢的宮]                宮位轉換

命主檔案欄位見 profiles/_template.json。年份一律指農曆年（干支年）。
"""

import argparse
import json
import sys

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
PALACES = ["命", "兄", "夫", "子", "財", "疾", "遷", "友", "官", "田", "福", "父"]
HUA = "祿權科忌"

SIHUA = {
    "甲": ["廉貞", "破軍", "武曲", "太陽"],
    "乙": ["天機", "天梁", "紫微", "太陰"],
    "丙": ["天同", "天機", "文昌", "廉貞"],
    "丁": ["太陰", "天同", "天機", "巨門"],
    "戊": ["貪狼", "太陰", "右弼", "天機"],
    "己": ["武曲", "貪狼", "天梁", "文曲"],
    "庚": ["太陽", "武曲", "太陰", "天同"],
    "辛": ["巨門", "太陽", "文曲", "文昌"],
    "壬": ["天梁", "紫微", "左輔", "武曲"],
    "癸": ["破軍", "巨門", "太陰", "貪狼"],
}

LU_CUN = dict(zip(STEMS, "寅卯巳午巳午申酉亥子"))
TIAN_KUI = dict(zip(STEMS, "丑子亥亥丑子丑午卯卯"))
TIAN_YUE = dict(zip(STEMS, "未申酉酉未申未寅巳巳"))
FLOW_CHANG = dict(zip(STEMS, "巳午申酉申酉亥子寅卯"))
FLOW_QU = dict(zip(STEMS, "酉申午巳午巳卯寅子亥"))

# 以年支序號 mod 4 分三合局：0 申子辰、1 巳酉丑、2 寅午戌、3 亥卯未
TIAN_MA = {0: "寅", 1: "亥", 2: "申", 3: "巳"}
HUO_LING_START = {0: ("寅", "戌"), 1: ("卯", "戌"), 2: ("丑", "卯"), 3: ("酉", "戌")}
XIAO_XIAN_START = {0: "戌", 1: "未", 2: "辰", 3: "丑"}

NAYIN = "金火木土金火水土金木水土火木水"
JU = {"水": 2, "木": 3, "金": 4, "土": 5, "火": 6}
JU_NAME = {2: "二", 3: "三", 4: "四", 5: "五", 6: "六"}

YIN = 2  # 寅宮的地支序號


def bi(branch):
    if branch not in BRANCHES:
        sys.exit(f"無效的地支：{branch}")
    return BRANCHES.index(branch)


def year_stem_branch(year):
    return STEMS[(year - 4) % 10], (year - 4) % 12


def yin_stem_index(stem):
    """五虎遁：該年干對應的寅宮（正月）天干序號。"""
    return (STEMS.index(stem) % 5 * 2 + 2) % 10


def ziwei_from_day(day, ju):
    pad = (-day) % ju
    quotient = (day + pad) // ju
    return (YIN + quotient - 1 + (pad if pad % 2 == 0 else -pad)) % 12


def palace_names(ming):
    """回傳 {地支序號: 宮名}，十二宮由命宮逆排。"""
    return {i: PALACES[(ming - i) % 12] for i in range(12)}


class Chart:
    def __init__(self, cfg):
        self.cfg = cfg
        self.warnings = []
        self.name = cfg.get("name", "")
        self.gender = cfg.get("gender")
        if self.gender not in ("男", "女"):
            sys.exit("gender 必須是「男」或「女」")
        self.birth_year = int(cfg["birth_year"])
        self.month = int(cfg["lunar_month"])
        if not 1 <= self.month <= 12:
            sys.exit("lunar_month 必須是 1–12")
        self.hour = bi(cfg["hour"])
        self.year_stem, self.year_branch = year_stem_branch(self.birth_year)

        self.sihua = {k: list(v) for k, v in SIHUA.items()}
        if cfg.get("geng_ke", "太陰") == "天府":
            self.sihua["庚"][2] = "天府"

        self.ming = (YIN + self.month - 1 - self.hour) % 12
        self.shen = (YIN + self.month - 1 + self.hour) % 12
        yin_stem = yin_stem_index(self.year_stem)
        self.stems = {i: STEMS[(yin_stem + (i - YIN) % 12) % 10] for i in range(12)}

        ming_stem = STEMS.index(self.stems[self.ming])
        self.element = NAYIN[((6 * ming_stem - 5 * self.ming) % 60 // 2) % 15]
        self.ju = JU[self.element]

        self.ziwei = self._resolve_ziwei()
        self.stars = self._place_stars()
        self.natal_names = palace_names(self.ming)

        yang = STEMS.index(self.year_stem) % 2 == 0
        self.direction = 1 if yang == (self.gender == "男") else -1

    def _resolve_ziwei(self):
        day = self.cfg.get("lunar_day")
        given = self.cfg.get("ziwei")
        if day is None and given is None:
            sys.exit("必須提供 lunar_day 或 ziwei（紫微所在地支）其中之一")
        if day is None:
            pos = bi(given)
            days = [d for d in range(1, 31) if ziwei_from_day(d, self.ju) == pos]
            if not days:
                sys.exit(f"{self.element}{JU_NAME[self.ju]}局沒有任何生日會令紫微落在{given}，請檢查月份與時辰")
            self.warnings.append(
                f"未提供農曆生日，紫微位置取自盤面（{given}）；可對應的生日：{'、'.join(map(str, days))}"
            )
            return pos
        pos = ziwei_from_day(int(day), self.ju)
        if given is not None and bi(given) != pos:
            self.warnings.append(
                f"盤面紫微在{given}，但依農曆{day}日與{self.element}{JU_NAME[self.ju]}局推算應在{BRANCHES[pos]}；"
                "以推算為準，請核對生日、月份或時辰"
            )
        return pos

    def _place_stars(self):
        z = self.ziwei
        f = (4 - z) % 12
        lu = bi(LU_CUN[self.year_stem])
        huo, ling = HUO_LING_START[self.year_branch % 4]
        m, h = self.month - 1, self.hour
        stars = {
            "紫微": z, "天機": z - 1, "太陽": z - 3, "武曲": z - 4, "天同": z - 5, "廉貞": z - 8,
            "天府": f, "太陰": f + 1, "貪狼": f + 2, "巨門": f + 3, "天相": f + 4,
            "天梁": f + 5, "七殺": f + 6, "破軍": f + 10,
            "文昌": bi("戌") - h, "文曲": bi("辰") + h,
            "左輔": bi("辰") + m, "右弼": bi("戌") - m,
            "天魁": bi(TIAN_KUI[self.year_stem]), "天鉞": bi(TIAN_YUE[self.year_stem]),
            "祿存": lu, "擎羊": lu + 1, "陀羅": lu - 1,
            "火星": bi(huo) + h, "鈴星": bi(ling) + h,
            "地劫": bi("亥") + h, "地空": bi("亥") - h,
            "天馬": bi(TIAN_MA[self.year_branch % 4]),
        }
        stars = {name: pos % 12 for name, pos in stars.items()}
        for key in ("extra_stars", "overrides"):
            for name, branch in (self.cfg.get(key) or {}).items():
                stars[name] = bi(branch)
        return stars

    def stars_in(self, i):
        return [name for name, pos in self.stars.items() if pos == i]

    def fly(self, i):
        """branch i 的宮干四化：回傳 [(化, 星, 落宮地支序號)]。"""
        return [(HUA[k], star, self.stars[star]) for k, star in enumerate(self.sihua[self.stems[i]])]

    def stem_hua(self, stem):
        return [(HUA[k], star, self.stars[star]) for k, star in enumerate(self.sihua[stem])]

    def decade_at(self, age):
        if age < self.ju:
            sys.exit(f"虛歲 {age} 尚未起大限（{self.element}{JU_NAME[self.ju]}局由 {self.ju} 歲起）")
        k = (age - self.ju) // 10
        branch = (self.ming + self.direction * k) % 12
        start = self.ju + 10 * k
        return branch, start, start + 9

    def decades(self):
        return {(self.ming + self.direction * k) % 12: self.ju + 10 * k for k in range(12)}

    def xiao_xian(self, age):
        start = bi(XIAO_XIAN_START[self.year_branch % 4])
        step = 1 if self.gender == "男" else -1
        return (start + step * (age - 1)) % 12


def table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(str(c) if c else "—" for c in row) + " |" for row in rows]
    return "\n".join(lines)


def label(names, i):
    return f"{names[i]}({BRANCHES[i]})"


def sitting_tags(chart, layers):
    """layers: [(層名, 天干)]。回傳 {地支序號: [坐守的四化]}。"""
    tags = {i: [] for i in range(12)}
    for layer, stem in layers:
        for hua, star, pos in chart.stem_hua(stem):
            tags[pos].append(f"{layer}{star}化{hua}")
    return tags


def layer_table(chart, layers, names):
    rows = []
    for layer, stem in layers:
        cells = [f"{star}→{label(names, pos)}" for _, star, pos in chart.stem_hua(stem)]
        ji_pos = chart.stem_hua(stem)[3][2]
        rows.append([layer, stem] + cells + [label(names, (ji_pos + 6) % 12)])
    return table(["層", "天干", "化祿", "化權", "化科", "化忌", "忌沖"], rows)


def ordered(names):
    """依宮序（命、兄、夫……父）回傳地支序號。"""
    return sorted(range(12), key=lambda i: PALACES.index(names[i]))


def flying_tables(chart, names):
    out_rows, in_rows = [], []
    incoming = {i: {h: [] for h in HUA} for i in range(12)}
    for i in range(12):
        for hua, _, pos in chart.fly(i):
            if pos != i:
                incoming[pos][hua].append(names[i])
    for i in ordered(names):
        cells = []
        for hua, star, pos in chart.fly(i):
            if pos == i:
                cell = f"{star} 自化{hua}"
            else:
                cell = f"{star}→{label(names, pos)}"
            if hua == "忌":
                cell += f"，沖{label(names, (pos + 6) % 12)}"
            cells.append(cell)
        out_rows.append([label(names, i), chart.stems[i]] + cells)
        inc = incoming[i]
        count = " ".join(f"{h}{len(inc[h])}" for h in HUA)
        in_rows.append([label(names, i)] + ["、".join(inc[h]) for h in HUA] + [count])
    text = "### 化出（各宮宮干四化的落點）\n\n"
    text += table(["宮", "宮干", "化祿", "化權", "化科", "化忌"], out_rows)
    text += "\n\n### 化入（其他宮宮干飛入本宮，不含自化）\n\n"
    text += table(["宮", "祿來自", "權來自", "科來自", "忌來自", "統計"], in_rows)
    return text


def loops(chart, names, k):
    nxt = lambda i: chart.stars[chart.sihua[chart.stems[i]][k]]
    found = []
    for start in range(12):
        path, i = [], start
        while i not in path:
            path.append(i)
            i = nxt(i)
        cycle = path[path.index(i):]
        pivot = cycle.index(min(cycle))
        cycle = cycle[pivot:] + cycle[:pivot]
        if cycle not in found:
            found.append(cycle)
    lines = []
    for cycle in found:
        if len(cycle) == 1:
            lines.append(f"- {label(names, cycle[0])} 自化{HUA[k]}（單宮循環）")
        else:
            lines.append("- " + " → ".join(label(names, i) for i in cycle) + f" → 回到 {names[cycle[0]]}")
    ming = next(i for i in range(12) if names[i] == "命")
    path, i = [], ming
    while i not in path:
        path.append(i)
        i = nxt(i)
    chain = " → ".join(label(names, j) for j in path) + f" → {label(names, i)}"
    return f"### 化{HUA[k]}循環\n\n" + "\n".join(lines) + f"\n\n由命宮追化{HUA[k]}：{chain}"


def taichi_table(chart, names, palace, tags):
    if palace not in PALACES:
        sys.exit(f"無效的宮名：{palace}（可用：{'、'.join(PALACES)}）")
    origin = next(i for i in range(12) if names[i] == palace)
    derived = palace_names(origin)
    rows = [
        [f"{palace}之{derived[i]}", label(names, i), "、".join(chart.stars_in(i)), "；".join(tags[i])]
        for i in ordered(derived)
    ]
    return f"### 以{palace}宮（{BRANCHES[origin]}）立太極\n\n" + table(
        ["轉換身分", "原宮", "星曜", "坐守四化"], rows
    )


def header(chart):
    lines = [
        f"命主：{chart.name or '（未命名）'}　{chart.gender}　"
        f"{chart.year_stem}{BRANCHES[chart.year_branch]}年（{chart.birth_year}）"
        f"農曆{chart.month}月{BRANCHES[chart.hour]}時",
        f"命宮：{BRANCHES[chart.ming]}（{chart.stems[chart.ming]}干）　身宮：{BRANCHES[chart.shen]}　"
        f"{chart.element}{JU_NAME[chart.ju]}局　紫微在{BRANCHES[chart.ziwei]}　"
        f"大限{'順' if chart.direction == 1 else '逆'}行　庚干化科：{chart.sihua['庚'][2]}",
    ]
    lines += [f"注意：{w}" for w in chart.warnings]
    return "\n".join(lines)


def self_hua(chart, i):
    return "、".join(f"{star}自化{hua}" for hua, star, pos in chart.fly(i) if pos == i)


def cmd_chart(chart, args):
    names = chart.natal_names
    layers = [("生年", chart.year_stem)]
    tags = sitting_tags(chart, layers)
    decades = chart.decades()
    rows = [
        [
            label(names, i) + ("・身" if i == chart.shen else ""),
            chart.stems[i],
            f"{decades[i]}–{decades[i] + 9}",
            "、".join(chart.stars_in(i)),
            "；".join(tags[i]),
            self_hua(chart, i),
        ]
        for i in ordered(names)
    ]
    print(header(chart) + "\n")
    print("## 本命盤\n")
    print(table(["本命宮", "宮干", "大限虛歲", "星曜", "生年四化", "自化"], rows) + "\n")
    print("### 生年四化（宮名為本命宮）\n")
    print(layer_table(chart, layers, names) + "\n")
    report(chart, names, tags, args)


def cmd_decade(chart, args):
    branch, start, end = chart.decade_at(args.age)
    stem = chart.stems[branch]
    names = palace_names(branch)
    layers = [("生年", chart.year_stem), ("大限", stem)]
    tags = sitting_tags(chart, layers)
    flow = flow_stars([("限", stem)])
    rows = [
        [
            label(names, i),
            chart.stems[i],
            chart.natal_names[i],
            "、".join(chart.stars_in(i)),
            "、".join(flow[i]),
            "；".join(tags[i]),
            self_hua(chart, i),
        ]
        for i in ordered(names)
    ]
    print(header(chart) + "\n")
    print(f"## 大限 {start}–{end} 虛歲：{stem}{BRANCHES[branch]}（本命{chart.natal_names[branch]}宮）\n")
    print("### 兩層四化（宮名為大限宮）\n")
    print(layer_table(chart, layers, names) + "\n")
    print(table(["大限宮", "宮干", "本命宮", "星曜", "限曜", "坐守四化", "自化"], rows) + "\n")
    report(chart, names, tags, args)


def flow_stars(stem_layers, year=None):
    """stem_layers: [(前綴, 天干)]；year: (天干, 地支序號) 時加上流年昌曲魁鉞馬。"""
    flow = {i: [] for i in range(12)}
    for prefix, stem in stem_layers:
        lu = bi(LU_CUN[stem])
        flow[lu].append(f"{prefix}祿")
        flow[(lu + 1) % 12].append(f"{prefix}羊")
        flow[(lu - 1) % 12].append(f"{prefix}陀")
    if year:
        stem, branch = year
        flow[bi(FLOW_CHANG[stem])].append("流昌")
        flow[bi(FLOW_QU[stem])].append("流曲")
        flow[bi(TIAN_KUI[stem])].append("流魁")
        flow[bi(TIAN_YUE[stem])].append("流鉞")
        flow[bi(TIAN_MA[branch % 4])].append("流馬")
    return flow


def cmd_year(chart, args):
    stem, branch = year_stem_branch(args.year)
    age = args.year - chart.birth_year + 1
    if age < 1:
        sys.exit("該年份早於出生年")
    d_branch, d_start, d_end = chart.decade_at(age)
    d_stem = chart.stems[d_branch]
    x_branch = chart.xiao_xian(age)
    x_stem = chart.stems[x_branch]
    names = palace_names(branch)
    d_names = palace_names(d_branch)
    layers = [("生年", chart.year_stem), ("大限", d_stem), ("流年", stem), ("小限", x_stem)]
    tags = sitting_tags(chart, layers)
    flow = flow_stars([("限", d_stem), ("流", stem)], (stem, branch))

    print(header(chart) + "\n")
    print(f"## 流年 {args.year} {stem}{BRANCHES[branch]}（虛歲 {age}）\n")
    print(f"- 大限：{d_start}–{d_end} 虛歲，{d_stem}{BRANCHES[d_branch]}（本命{chart.natal_names[d_branch]}宮）")
    print(f"- 小限：{x_stem}{BRANCHES[x_branch]}（流年{names[x_branch]}宮、本命{chart.natal_names[x_branch]}宮）")
    print(f"- 流年命宮：{BRANCHES[branch]}（大限{d_names[branch]}宮、本命{chart.natal_names[branch]}宮）")
    print("- 流年以農曆年計；春節（或所用流派的立春）前仍屬上一年\n")
    print("### 四層四化（宮名為流年宮）\n")
    print(layer_table(chart, layers, names) + "\n")
    rows = [
        [
            label(names, i),
            chart.stems[i],
            d_names[i],
            chart.natal_names[i],
            "、".join(chart.stars_in(i)),
            "、".join(flow[i]),
            "；".join(tags[i]),
            self_hua(chart, i),
        ]
        for i in ordered(names)
    ]
    print("### 疊宮\n")
    print(table(["流年宮", "宮干", "大限宮", "本命宮", "星曜", "流曜", "坐守四化", "自化"], rows) + "\n")
    report(chart, names, tags, args)

    dou_jun = (branch - (chart.month - 1) + chart.hour) % 12
    yin_stem = yin_stem_index(stem)
    month_rows = []
    for m in range(12):
        pos = (dou_jun + m) % 12
        m_stem = STEMS[(yin_stem + m) % 10]
        hua = " ".join(f"{star}{h}→{names[p]}" for h, star, p in chart.stem_hua(m_stem))
        month_rows.append([m + 1, label(names, pos), chart.natal_names[pos], f"{m_stem}{BRANCHES[(YIN + m) % 12]}", hua])
    print(f"\n### 流月（斗君在{BRANCHES[dou_jun]}，四化用月干，落宮以流年宮名表示）\n")
    print(table(["農曆月", "流月命宮", "本命宮", "月干支", "月干四化"], month_rows))


def report(chart, names, tags, args):
    print(flying_tables(chart, names) + "\n")
    print(loops(chart, names, 0) + "\n")
    print(loops(chart, names, 3))
    if args.taichi:
        print()
        print(taichi_table(chart, names, args.taichi, tags))


def cmd_convert(args):
    idx = PALACES.index
    for p in (args.taichi_palace, args.target):
        if p and p not in PALACES:
            sys.exit(f"無效的宮名：{p}（可用：{'、'.join(PALACES)}）")
    if args.taichi_palace and args.target:
        role = PALACES[(idx(args.target) - idx(args.taichi_palace)) % 12]
        print(f"{args.target}宮是{args.taichi_palace}宮的{role}宮")
    elif args.taichi_palace:
        a = args.taichi_palace
        print(table(["宮", f"相對於{a}宮"], [[b, f"{a}之{PALACES[(idx(b) - idx(a)) % 12]}"] for b in PALACES]))
    else:
        rows = [[b] + [PALACES[(idx(b) - idx(a)) % 12] for a in PALACES] for b in PALACES]
        print(table(["宮 \\ 太極"] + PALACES, rows))


def main():
    parser = argparse.ArgumentParser(description="紫微斗數排盤與宮干飛化計算")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, extra in (("chart", None), ("decade", "age"), ("year", "year")):
        p = sub.add_parser(name)
        p.add_argument("profile", help="命主檔案（JSON）")
        if extra:
            p.add_argument(extra, type=int, help="虛歲" if extra == "age" else "西元年（農曆年）")
        p.add_argument("--taichi", help="另以此宮立太極，列出十二個轉換身分")
    p = sub.add_parser("convert")
    p.add_argument("taichi_palace", nargs="?", help="作為太極點的宮")
    p.add_argument("target", nargs="?", help="被查詢的宮")
    args = parser.parse_args()

    if args.cmd == "convert":
        cmd_convert(args)
        return
    with open(args.profile, encoding="utf-8") as fh:
        chart = Chart(json.load(fh))
    {"chart": cmd_chart, "decade": cmd_decade, "year": cmd_year}[args.cmd](chart, args)


if __name__ == "__main__":
    main()
