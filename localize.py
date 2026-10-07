#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
localize.py —— 把镜像下来的 mathartbang 地图站汉化。

译名来源：hunter-wiki.cn（theHunter COTW 中文资料），即游戏官方简中的用法。
标了「待核」的条目是没查到官方页、暂用通用译名的，遇到再改即可。

只动「显示用的文字」：
  * HTML 里的标题、按钮、菜单，以及 map.html 里用模板字符串拼的标签
  * layers.json 里图层的 name / attribution
  * reserve.json 里 population_info[..].population_name
绝对不动：id / url / layer_type / bounds 等程序字段。

用法:
    python localize.py --site site            # 原地汉化
    python localize.py --site site --out site-zh
"""

import argparse
import glob
import json
import os
import re
import shutil
import sys

# ------------------------------------------------------------------ 区域类型
ZONES = {
    "spawn": "刷新区",
    "drinking": "饮水区",
    "feeding": "进食区",
    "resting": "休息区",
    "flee": "逃跑区",
    "forbidden": "禁入区",
    "climb forbidden": "禁攀爬区",
    "water": "水域",
    "waterfowl_forbidden": "水禽禁入区",
    "alligator_forbidden": "鳄鱼禁入区",
    "shoreline": "岸线",
}

# ------------------------------------------------------------------ 兴趣点分类
POI_TYPES = {
    "hunting_blind": "狩猎掩体",
    "landmark": "地标",
    "lookout_point": "瞭望点",
    "outpost": "前哨站",
    "lore": "收集品",
    "boat_crossing": "渡口",
    "machan": "狩猎高台",
    "shooting_range": "靶场",
    "unknown_54": "未分类54",
    "unknown_66": "未分类66",
}

# ------------------------------------------------------------------ 物种（官方译名）
SPECIES = {
    "Alpine Goat": "高山山羊",          # 待核
    "American Alligator": "美洲短吻鳄",
    "American Mink": "美洲水貂",
    "Antelope Jackrabbit": "羚羊兔",
    "Axis Deer": "斑轴鹿", "axis_deer": "斑轴鹿",
    "Barasingha": "沼鹿",
    "Beceite Ibex": "贝塞特山羊",
    "Bengal Tiger": "孟加拉虎",
    "Bighorn Sheep": "大角羊",          # 待核
    "Black Bear": "黑熊",               # 待核
    "Black Caiman": "黑凯门鳄",         # 待核
    "Black Grouse": "黑琴鸡",
    "Blackbuck": "印度黑羚",            # 待核
    "Blacktail Deer": "黑尾鹿",
    "Blue Sheep": "岩羊",
    "Blue Wildebeest": "蓝角马",
    "Bobwhite Quail": "山齿鹑",
    "Northern Bobwhite Quail": "山齿鹑",
    "Brown Bear": "棕熊",               # 待核
    "Canada Goose": "黑额黑雁",
    "Cape Buffalo": "非洲水牛",         # 待核
    "Capybara": "水豚",                 # 待核
    "Caribou": "驯鹿",                  # 待核（官方页面 500，与 Reindeer 同）
    "Chamois": "臆羚",
    "Cinnamon Teal": "桂红水鸭",
    "Collared Peccary": "领西猯",       # 待核
    "Coyote": "郊狼",                   # 待核
    "Dusky Grouse": "蓝镰翅鸡",
    "EU Bison": "欧洲野牛", "European Bison": "欧洲野牛",
    "EU Rabbit": "欧洲兔",              # 待核
    "Eastern Cottontail Rabbit": "东部白尾灰兔",
    "Eastern Wild Turkey": "东部野生火鸡",
    "Eurasian Pine Marten": "欧亚松貂",
    "Eurasian Teal": "绿翅鸭",
    "Eurasian Wigeon": "赤颈鸭",        # 待核
    "Eurasian Woodcock": "欧亚丘鹬",
    "European Badger": "欧洲獾",        # 待核
    "European Hare": "欧洲野兔",        # 待核
    "Fallow Deer": "黇鹿", "fallow_deer": "黇鹿",
    "Feral Goat": "野山羊", "feral_goat": "野山羊",
    "Feral Pig": "野化家猪", "feral_pig": "野化家猪",   # 待核
    "Ferruginous Duck": "白眼潜鸭",
    "Gadwall": "赤膀鸭",
    "Gemsbok": "南非剑羚",              # 待核
    "GoldenEye": "鹊鸭",                # 待核
    "Gray Fox": "灰狐",                 # 待核
    "Gray Wolf": "灰狼",
    "Greater Grison": "大巢鼬",         # 待核
    "Gredos Ibex": "格雷多斯山羊",
    "Green Wing Teal": "美洲绿翅鸭",    # 待核
    "Greylag Goose": "灰雁",
    "Grizzly Bear": "灰熊",
    "Harlequin Duck": "丑鸭",
    "Hazel Grouse": "花尾榛鸡",
    "Iberian Mouflon": "伊比利亚摩弗伦羊",
    "Iberian Wolf": "伊比利亚狼",
    "Jack Rabbit": "长耳兔",            # 待核
    "Jaguar": "美洲豹",                 # 待核
    "Javan Rusa": "鬣鹿", "javan_rusa": "鬣鹿",
    "Lesser Kudu": "小旋角羚",
    "Lion": "狮",                       # 待核
    "Lynx": "猞猁",                     # 待核
    "Mallard": "绿头鸭",
    "Manitoban Elk": "马尼托巴麋鹿",
    "Mexican Bobcat": "墨西哥短尾猫",   # 待核
    "Moose": "驼鹿",
    "Mountain Goat": "北美野山羊",
    "Mountain Hare": "高山兔",          # 待核
    "Mule Deer": "骡鹿",
    "Musk Deer": "麝",                  # 待核
    "Nilgai": "蓝牛羚",                 # 待核
    "North American Beaver": "北美河狸",
    "Northern Pintail": "针尾鸭",
    "Northern Red Muntjac": "北方赤麂",
    "Ocelot": "虎猫",                   # 待核
    "Pheasant": "环颈雉鸡",
    "Plains Bison": "美洲平原野牛",
    "Prong Horn": "叉角羚", "Pronghorn": "叉角羚",
    "Puma": "美洲狮",                   # 待核
    "Raccoon": "浣熊",                  # 待核
    "Raccoon Dog": "貉",                # 待核
    "Red Deer": "赤鹿", "red_deer": "赤鹿",
    "Red Fox": "赤狐", "red_fox": "赤狐",
    "Red Grouse": "红松鸡",
    "Reindeer": "驯鹿",                 # 待核
    "Rio Grande Turkey": "格兰德火鸡",
    "Rock Ptarmigan": "岩雷鸟",
    "Rockymountain Elk": "落基山麋鹿",  # 待核
    "Roe Deer": "狍", "Roe_Deer": "狍", "roe_deer": "狍",
    "Ronda Ibex": "龙达山羊",           # 待核
    "Roosevelt Elk": "罗斯福麋鹿",
    "Saltwater Crocodile": "湾鳄", "saltwater_crocodile": "湾鳄",   # 待核
    "Sambar": "黑鹿", "sambar": "黑鹿",
    "Scrub Hare": "薮兔",
    "Side-striped Jackal": "侧纹胡狼",  # 待核
    "Sika Deer": "梅花鹿",              # 待核
    "Snow Goose": "雪雁",
    "Snow Leopard": "雪豹",             # 待核
    "South American Tapir": "南美貘",   # 待核
    "Southeastern Ibex": "东南山羊",    # 待核
    "Spectacled Bear": "眼镜熊",        # 待核
    "Springbok": "跳羚",                # 待核
    "Stubble Quail": "澳洲鹌鹑", "stubble_quail": "澳洲鹌鹑",
    "Tahr": "塔尔羊",                   # 待核
    "Taruca": "塔鲁卡鹿",               # 待核
    "Tibetan Fox": "藏狐",
    "Tufted Duck": "凤头潜鸭",
    "Tundra Bean Goose": "冻原豆雁",
    "Vicuna": "小羊驼",                 # 待核
    "Warthog": "疣猪",
    "Water Buffalo": "水牛",
    "Western Capercaillie": "西方松鸡",
    "Western Mountain Coati": "山长鼻浣熊",   # 待核
    "Whitetail": "白尾鹿", "Whitetail Deer": "白尾鹿",
    "Wild Boar": "野猪",
    "Wild Haggis": "野哈吉斯",          # 待核
    "Wild Turkey": "野火鸡",            # 待核
    "Wild Yak": "野牦牛",
    "Willow Ptarmigan": "柳雷鸟",
    "Wood Bison": "森林野牛",           # 待核
    "Wood Duck": "林鸳鸯",              # 待核
    "Woolly Hare": "高原兔",
    "banteng": "爪哇野牛",
    "bobcat": "短尾猫",                 # 待核
    "eastern_grey_kangaroo": "东部灰袋鼠",   # 待核
    "hog_deer": "豚鹿",                 # 待核
    "magpie_goose": "鹊雁",
    # 特殊图层
    "Animal Forbidden Map": "动物禁入图",
    "Aquatic Animals Flee Map": "水生动物逃跑图",
    "Climb Forbidden Map": "禁攀爬图",
    "Flee Map": "逃跑图",
    "Water Map": "水域图",
}

FULL_NAME_OVERRIDES = {"Topographic": "等高线底图"}

# ------------------------------------------------------------------ 保护区（官方译名）
RESERVES = {
    "Hirschfelden Hunting Reserve": "赫希费尔登狩猎保护区",
    "Layton Lake District": "莱顿湖区",
    "Medved-Taiga National Park": "梅德韦泰嘉国家公园",
    "Vurhonga Savanna": "乌尔霍加热带稀树草原",
    "Parque Fernando": "费南多自然公园",
    "Yukon Valley Nature Reserve": "育空河谷自然保护区",
    "Cuatro Colinas Game Reserve": "夸特罗·科利纳斯野生动物保护区",
    "Silver Ridge Peaks": "银岭峰",
    "Te Awaroa National Park": "蒂阿拉罗瓦国家公园",
    "Rancho Del Arroyo": "阿罗约大牧场",              # 待核
    "Mississippi Acres Preserve": "密西西比阿克里斯保护区",
    "Revontuli Coast": "雷文图里海岸",
    "New England Mountains": "新英格兰山脉",
    "Emerald Coast Australia": "澳大利亚翡翠海岸",     # 待核
    "Sundarpatan Hunting Reserve": "孙达尔帕坦狩猎保护区",  # 待核
    "Salzwiesen Park": "萨尔茨维森公园",
    "Askiy Ridge Hunting Preserve": "阿斯基岭狩猎保护区",
    "Tòrr Nan Sìthean Hunting Estate": "精灵之丘狩猎庄园",
    "Intisuyu Hunting Reserve": "因蒂苏尤狩猎保护区",  # 待核
}

RESERVE_BUTTONS = {
    "Hirschfelden<br/>Hunting Reserve": "赫希费尔登<br/>狩猎保护区",
    "Layton Lake<br/>District": "莱顿湖<br/>区",
    "Medved-Taiga<br/>National Park": "梅德韦泰嘉<br/>国家公园",
    "Vurhonga<br/>Savanna": "乌尔霍加<br/>热带稀树草原",
    "Parque<br/>Fernando": "费南多<br/>自然公园",
    "Yukon Valley<br/>Nature Reserve": "育空河谷<br/>自然保护区",
    "Cuatro Colinas<br/>Game Reserve": "夸特罗·科利纳斯<br/>野生动物保护区",
    "Silver Ridge<br/>Peaks": "银岭<br/>峰",
    "Te Awaroa<br/>National Park": "蒂阿拉罗瓦<br/>国家公园",
    "Rancho<br/>Del Arroyo": "阿罗约<br/>大牧场",
    "Mississippi<br/>Acres Preserve": "密西西比<br/>阿克里斯保护区",
    "Revontuli<br/>Coast": "雷文图里<br/>海岸",
    "New England<br/>Mountains": "新英格兰<br/>山脉",
    "Emerald Coast<br/>Australia": "翡翠海岸<br/>澳大利亚",
    "Sundarpatan<br/>Hunting Reserve": "孙达尔帕坦<br/>狩猎保护区",
    "Salzwiesen<br/>Park": "萨尔茨维森<br/>公园",
    "Askiy Ridge<br/>Hunting Preserve": "阿斯基岭<br/>狩猎保护区",
    "Tòrr Nan Sìthean<br/>Hunting Estate": "精灵之丘<br/>狩猎庄园",
    "Intisuyu<br/>Hunting Reserve": "因蒂苏尤<br/>狩猎保护区",
}

# ------------------------------------------------------------------ 界面文字
UI = {
    "DECA: The Hunter: COTW Map": "DECA：猎人：荒野的呼唤 · 地图",
    "DECA: theHunter:COTWMap & Encyclopedia": "DECA：猎人：荒野的呼唤 · 地图与图鉴",
    "DECA: theHunter:COTW Map & Encyclopedia": "DECA：猎人：荒野的呼唤 · 地图与图鉴",
    "DECA: The Hunter:COTW Save Utility": "DECA：猎人：荒野的呼唤 · 存档工具",
    "LOADING GAME DATA ...": "正在加载游戏数据……",
    "LOADING GAME DATA": "正在加载游戏数据",
    "Main Page": "主页",
    "Home": "首页",
    "Report Bugs/Make Requests": "反馈问题 / 提需求",
    "DROPZONE": "把文件拖到这里",
    "Maps": "地图",
    "Contents": "目录",
    "Tools": "工具",
    "Zones": "区域类型",
    "Reserves": "保护区",
    "Save File Visualization": "存档可视化",
    "Movement Schedule and Zones per Population, Spawn Zone, and Group":
        "各群体的活动时间表与区域（按种群、刷新区、群组）",
    "Max Score per Population, Spawn Zone, and Group":
        "各群体的最高评分（按种群、刷新区、群组）",
    "Hunting Pressure Map": "狩猎压力图",
    "lookout points": "瞭望点",
    "landmarks": "地标",
    "outposts": "前哨站",
    "hunting blinds": "狩猎掩体",
    "lore": "收集品",
    "shooting ranges": "靶场",
    "theHunter:COTW Save Directory/Files Decompressor":
        "theHunter:COTW 存档目录 / 文件解压工具",
    "As of the 2020-08-11 release theHunter:COTW compresses save files, this tool decompresses the save files":
        "自 2020-08-11 版本起，theHunter:COTW 会压缩存档文件，这个工具用来解压存档。",
    "Support Me on Ko-fi": "在 Ko-fi 上支持我",
}

# map.html 里用反引号拼出来的标签
JS_LABELS = {
    "Population: ": "种群：",
    "Spawn Area: ": "刷新区：",
    "Group Index: ": "群组序号：",
    "Max Score: ": "最高分：",
    "Great One (maybe?): ": "大角个体(可能)：",
    "Animal Count: ": "动物数量：",
    "Zone Type: ": "区域类型：",
    "Spawn: ": "刷新区：",
    "Group: ": "群组：",
    "User HeatMap": "玩家热力图",
}

POI_OVERLAY_OLD = "overlayMaps['POI: ' + poi_type]"
POI_OVERLAY_NEW = (
    "overlayMaps['兴趣点：' + ("
    + json.dumps(POI_TYPES, ensure_ascii=False)
    + "[poi_type] || poi_type)]"
)


def tr_text(s):
    # 保护区全名都够长，直接全局替换
    for en in sorted(RESERVES, key=len, reverse=True):
        s = s.replace(en, RESERVES[en])
    for en in sorted(UI, key=len, reverse=True):
        if len(en) <= 12:
            # 短词（Maps / Tools / Home …）只替换「作为独立文本」出现的地方，
            # 否则会把 JS 标识符改坏，例如 overlayMaps -> overlay地图
            s = re.sub(
                r">(\s*)" + re.escape(en) + r"(\s*)<",
                lambda m: ">" + m.group(1) + UI[en] + m.group(2) + "<",
                s,
            )
        else:
            s = s.replace(en, UI[en])
    return s


def localize_html(path):
    with open(path, encoding="utf-8") as f:
        t = f.read()
    orig = t
    for en in sorted(RESERVE_BUTTONS, key=len, reverse=True):
        t = t.replace(en, RESERVE_BUTTONS[en])
    # JS 里的具体表达式先换掉，避免被后面的通用替换切碎
    if POI_OVERLAY_OLD in t:
        t = t.replace(POI_OVERLAY_OLD, POI_OVERLAY_NEW)
    for en in sorted(JS_LABELS, key=len, reverse=True):
        t = t.replace(en, JS_LABELS[en])
    t = tr_text(t)
    if t != orig:
        with open(path, "w", encoding="utf-8") as f:
            f.write(t)
        return True
    return False


def _tr_species(name, pid=None):
    """优先按显示名查，查不到再按 population_id 查"""
    if isinstance(name, str) and name in SPECIES:
        return SPECIES[name]
    if isinstance(pid, str) and pid in SPECIES:
        return SPECIES[pid]
    return None


def localize_layers(path):
    with open(path, encoding="utf-8") as f:
        layers = json.load(f)
    if not isinstance(layers, list):
        return False
    changed = False
    for L in layers:
        name = L.get("name")
        if isinstance(name, str):
            new = FULL_NAME_OVERRIDES.get(name)
            if new is None:
                if ": " in name:
                    sp, zo = name.rsplit(": ", 1)
                    new = "%s：%s" % (_tr_species(sp) or sp, ZONES.get(zo, zo))
                else:
                    new = _tr_species(name) or name
            if new != name:
                L["name"] = new
                changed = True
        attr = L.get("attribution")
        if isinstance(attr, str) and attr:
            new = attr.replace(" bitmaps from ", " 热力图 · 来源：").replace(" map from ", " 地图 · 来源：")
            for en in sorted(RESERVES, key=len, reverse=True):
                new = new.replace(en, RESERVES[en])
            if new != attr:
                L["attribution"] = new
                changed = True
    if changed:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(layers, f, ensure_ascii=False, separators=(",", ":"))
    return changed


def localize_reserve(path):
    """只改 population_info 里显示用的 population_name，population_id 不动"""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    pi = d.get("population_info")
    if not isinstance(pi, dict):
        return False
    changed = False
    for v in pi.values():
        if not isinstance(v, dict):
            continue
        zh = _tr_species(v.get("population_name"), v.get("population_id"))
        if zh and zh != v.get("population_name"):
            v["population_name"] = zh
            changed = True
    if changed:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, separators=(",", ":"))
    return changed


def main(argv=None):
    ap = argparse.ArgumentParser(description="汉化镜像下来的站点（只改显示文字）")
    ap.add_argument("--site", default="site")
    ap.add_argument("--out", default=None, help="另存到该目录；不给则原地修改")
    a = ap.parse_args(argv)

    if not os.path.isdir(a.site):
        print("[localize] 找不到目录 %s" % a.site, file=sys.stderr)
        return 1

    if a.out and os.path.abspath(a.out) != os.path.abspath(a.site):
        if os.path.exists(a.out):
            shutil.rmtree(a.out)
        shutil.copytree(a.site, a.out)
    target = a.out or a.site

    n_html = n_layers = n_res = 0
    for p in glob.glob(os.path.join(target, "**", "*.html"), recursive=True):
        if localize_html(p):
            n_html += 1
    for p in glob.glob(os.path.join(target, "**", "layers.json"), recursive=True):
        if localize_layers(p):
            n_layers += 1
    for p in glob.glob(os.path.join(target, "**", "reserve.json"), recursive=True):
        if localize_reserve(p):
            n_res += 1

    print("[localize] 完成：HTML %d，layers.json %d，reserve.json %d -> %s"
          % (n_html, n_layers, n_res, target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
