#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
localize.py —— 把镜像下来的 mathartbang 地图站汉化。

只动「显示用的文字」：
  * HTML 里的标题、按钮、菜单
  * layers.json 里图层的 name（就是右侧图层列表）和 attribution 署名

绝对不动：id / url / layer_type / bounds 等程序字段——
翻错了地图会直接散架，所以这里全部走「精确匹配整串」，不做模糊替换。

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
    "feeding": "觅食区",
    "resting": "休息区",
    "flee": "逃跑区",
    "forbidden": "禁入区",
    "climb forbidden": "禁攀爬区",
    "water": "水域",
    "waterfowl_forbidden": "水禽禁入区",
    "alligator_forbidden": "鳄鱼禁入区",
    "shoreline": "岸线",
}

# ------------------------------------------------------------------ 物种
SPECIES = {
    "Alpine Goat": "高山山羊",
    "American Alligator": "美洲短吻鳄",
    "American Mink": "美洲水貂",
    "Antelope Jackrabbit": "羚羊兔",
    "Axis Deer": "花鹿", "axis_deer": "花鹿",
    "Barasingha": "沼鹿",
    "Beceite Ibex": "贝塞特野山羊",
    "Bengal Tiger": "孟加拉虎",
    "Bighorn Sheep": "大角羊",
    "Black Bear": "黑熊",
    "Black Caiman": "黑凯门鳄",
    "Black Grouse": "黑琴鸡",
    "Blackbuck": "印度黑羚",
    "Blacktail Deer": "黑尾鹿",
    "Blue Sheep": "岩羊",
    "Blue Wildebeest": "蓝角马",
    "Brown Bear": "棕熊",
    "Canada Goose": "加拿大黑雁",
    "Cape Buffalo": "非洲水牛",
    "Capybara": "水豚",
    "Caribou": "驯鹿",
    "Chamois": "岩羚羊",
    "Cinnamon Teal": "桂红鸭",
    "Collared Peccary": "领西猯",
    "Coyote": "郊狼",
    "Dusky Grouse": "蓝镰翅鸡",
    "EU Bison": "欧洲野牛",
    "EU Rabbit": "欧洲兔",
    "Eastern Cottontail Rabbit": "东部棉尾兔",
    "Eastern Wild Turkey": "东部野火鸡",
    "Eurasian Pine Marten": "松貂",
    "Eurasian Teal": "绿翅鸭",
    "Eurasian Wigeon": "赤颈鸭",
    "Eurasian Woodcock": "丘鹬",
    "European Badger": "欧洲獾",
    "European Hare": "欧洲野兔",
    "Fallow Deer": "黇鹿", "fallow_deer": "黇鹿",
    "Feral Goat": "野化山羊", "feral_goat": "野化山羊",
    "Feral Pig": "野化家猪", "feral_pig": "野化家猪",
    "Ferruginous Duck": "白眼潜鸭",
    "Gadwall": "赤膀鸭",
    "Gemsbok": "南非剑羚",
    "GoldenEye": "鹊鸭",
    "Gray Fox": "灰狐",
    "Gray Wolf": "灰狼",
    "Greater Grison": "大巢鼬",
    "Gredos Ibex": "格雷多斯野山羊",
    "Green Wing Teal": "美洲绿翅鸭",
    "Greylag Goose": "灰雁",
    "Grizzly Bear": "灰熊",
    "Harlequin Duck": "丑鸭",
    "Hazel Grouse": "花尾榛鸡",
    "Iberian Mouflon": "伊比利亚盘羊",
    "Iberian Wolf": "伊比利亚狼",
    "Jack Rabbit": "长耳兔",
    "Jaguar": "美洲豹",
    "Lesser Kudu": "小捻角羚",
    "Lion": "狮",
    "Lynx": "猞猁",
    "Mallard": "绿头鸭",
    "Manitoban Elk": "马尼托巴马鹿",
    "Mexican Bobcat": "墨西哥短尾猫",
    "Moose": "驼鹿",
    "Mountain Goat": "雪羊",
    "Mountain Hare": "高山兔",
    "Mule Deer": "骡鹿",
    "Musk Deer": "麝",
    "Nilgai": "蓝牛羚",
    "North American Beaver": "美洲河狸",
    "Northern Bobwhite Quail": "山齿鹑",
    "Northern Pintail": "针尾鸭",
    "Northern Red Muntjac": "赤麂",
    "Ocelot": "虎猫",
    "Pheasant": "雉鸡",
    "Plains Bison": "美洲草原野牛",
    "Prong Horn": "叉角羚",
    "Puma": "美洲狮",
    "Raccoon": "浣熊",
    "Raccoon Dog": "貉",
    "Red Deer": "马鹿", "red_deer": "马鹿",
    "Red Fox": "赤狐", "red_fox": "赤狐",
    "Red Grouse": "红松鸡",
    "Reindeer": "驯鹿",
    "Rio Grande Turkey": "里奥格兰德火鸡",
    "Rock Ptarmigan": "雷鸟",
    "Rockymountain Elk": "落基山马鹿",
    "Roe Deer": "狍", "Roe_Deer": "狍",
    "Ronda Ibex": "龙达野山羊",
    "Roosevelt Elk": "罗斯福马鹿",
    "Scrub Hare": "灌丛野兔",
    "Side-striped Jackal": "侧纹胡狼",
    "Sika Deer": "梅花鹿",
    "Snow Goose": "雪雁",
    "Snow Leopard": "雪豹",
    "South American Tapir": "南美貘",
    "Southeastern Ibex": "东南野山羊",
    "Spectacled Bear": "眼镜熊",
    "Springbok": "跳羚",
    "Tahr": "塔尔羊",
    "Taruca": "塔鲁卡鹿",
    "Tibetan Fox": "藏狐",
    "Tufted Duck": "凤头潜鸭",
    "Tundra Bean Goose": "冻原豆雁",
    "Vicuna": "小羊驼",
    "Warthog": "疣猪",
    "Water Buffalo": "水牛",
    "Western Capercaillie": "松鸡",
    "Western Mountain Coati": "山长鼻浣熊",
    "Whitetail": "白尾鹿",
    "Whitetail Deer": "白尾鹿",
    "Wild Boar": "野猪",
    "Wild Haggis": "野哈吉斯",
    "Wild Turkey": "野火鸡",
    "Wild Yak": "野牦牛",
    "Willow Ptarmigan": "柳雷鸟",
    "Wood Bison": "森林野牛",
    "Wood Duck": "林鸳鸯",
    "Woolly Hare": "绒毛兔",
    # 只有下划线的写法
    "banteng": "爪哇野牛",
    "bobcat": "短尾猫",
    "eastern_grey_kangaroo": "东部灰袋鼠",
    "hog_deer": "豚鹿",
    "javan_rusa": "爪哇水鹿",
    "magpie_goose": "鹊雁",
    "saltwater_crocodile": "湾鳄",
    "sambar": "水鹿",
    "stubble_quail": "鹌鹑",
    # 特殊图层
    "Animal Forbidden Map": "动物禁入图",
    "Aquatic Animals Flee Map": "水生动物逃跑图",
    "Climb Forbidden Map": "禁攀爬图",
    "Flee Map": "逃跑图",
    "Water Map": "水域图",
}

# 整个名字的例外（不做「物种: 区域」拆分）
FULL_NAME_OVERRIDES = {
    "Topographic": "等高线底图",
}

# ------------------------------------------------------------------ 保护区
RESERVES = {
    "Hirschfelden Hunting Reserve": "赫希费尔登狩猎保护区",
    "Layton Lake District": "莱顿湖区",
    "Medved-Taiga National Park": "梅德韦泰加国家公园",
    "Vurhonga Savanna": "弗洪加稀树草原",
    "Parque Fernando": "费尔南多公园",
    "Yukon Valley Nature Reserve": "育空河谷自然保护区",
    "Cuatro Colinas Game Reserve": "夸特罗科利纳斯狩猎区",
    "Silver Ridge Peaks": "银岭峰",
    "Te Awaroa National Park": "特阿瓦罗阿国家公园",
    "Rancho Del Arroyo": "阿罗约牧场",
    "Mississippi Acres Preserve": "密西西比庄园保护区",
    "Revontuli Coast": "雷文图里海岸",
    "New England Mountains": "新英格兰山脉",
    "Emerald Coast Australia": "澳大利亚翡翠海岸",
    "Sundarpatan Hunting Reserve": "孙达尔帕坦狩猎保护区",
    "Salzwiesen Park": "萨尔茨维森公园",
    "Askiy Ridge Hunting Preserve": "阿斯基岭狩猎保护区",
    "Tòrr Nan Sìthean Hunting Estate": "托尔南西森狩猎庄园",
    "Intisuyu Hunting Reserve": "因蒂苏尤狩猎保护区",
}

# map.html 里按钮是 "上面一行<br/>下面一行" 的形式
RESERVE_BUTTONS = {
    "Hirschfelden<br/>Hunting Reserve": "赫希费尔登<br/>狩猎保护区",
    "Layton Lake<br/>District": "莱顿湖<br/>区",
    "Medved-Taiga<br/>National Park": "梅德韦泰加<br/>国家公园",
    "Vurhonga<br/>Savanna": "弗洪加<br/>稀树草原",
    "Parque<br/>Fernando": "费尔南多<br/>公园",
    "Yukon Valley<br/>Nature Reserve": "育空河谷<br/>自然保护区",
    "Cuatro Colinas<br/>Game Reserve": "夸特罗科利纳斯<br/>狩猎区",
    "Silver Ridge<br/>Peaks": "银岭<br/>峰",
    "Te Awaroa<br/>National Park": "特阿瓦罗阿<br/>国家公园",
    "Rancho<br/>Del Arroyo": "阿罗约<br/>牧场",
    "Mississippi<br/>Acres Preserve": "密西西比<br/>庄园保护区",
    "Revontuli<br/>Coast": "雷文图里<br/>海岸",
    "New England<br/>Mountains": "新英格兰<br/>山脉",
    "Emerald Coast<br/>Australia": "翡翠海岸<br/>澳大利亚",
    "Sundarpatan<br/>Hunting Reserve": "孙达尔帕坦<br/>狩猎保护区",
    "Salzwiesen<br/>Park": "萨尔茨维森<br/>公园",
    "Askiy Ridge<br/>Hunting Preserve": "阿斯基岭<br/>狩猟保护区",
    "Tòrr Nan Sìthean<br/>Hunting Estate": "托尔南西森<br/>狩猎庄园",
    "Intisuyu<br/>Hunting Reserve": "因蒂苏尤<br/>狩猎保护区",
}

# ------------------------------------------------------------------ 其它界面文字
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


def tr_text(s):
    """对一段纯文本套用保护区名 + 界面词替换"""
    for en in sorted(RESERVES, key=len, reverse=True):
        s = s.replace(en, RESERVES[en])
    for en in sorted(UI, key=len, reverse=True):
        s = s.replace(en, UI[en])
    return s


def localize_html(path):
    with open(path, encoding="utf-8") as f:
        t = f.read()
    orig = t
    # 保护区按钮（带 <br/>）先处理，避免被后面的整名替换切碎
    for en in sorted(RESERVE_BUTTONS, key=len, reverse=True):
        t = t.replace(en, RESERVE_BUTTONS[en])
    t = tr_text(t)
    if t != orig:
        with open(path, "w", encoding="utf-8") as f:
            f.write(t)
        return True
    return False


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
                    new = "%s：%s" % (SPECIES.get(sp, sp), ZONES.get(zo, zo))
                else:
                    new = SPECIES.get(name, name)
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


def main(argv=None):
    ap = argparse.ArgumentParser(description="汉化镜像下来的站点（只改显示文字）")
    ap.add_argument("--site", default="site", help="镜像目录")
    ap.add_argument("--out", default=None, help="另存到该目录；不给则原地修改")
    a = ap.parse_args(argv)

    if not os.path.isdir(a.site):
        print(f"[localize] 找不到目录 {a.site}", file=sys.stderr)
        return 1

    if a.out and os.path.abspath(a.out) != os.path.abspath(a.site):
        if os.path.exists(a.out):
            shutil.rmtree(a.out)
        shutil.copytree(a.site, a.out)
    target = a.out or a.site

    n_html = n_json = 0
    for p in glob.glob(os.path.join(target, "**", "*.html"), recursive=True):
        if localize_html(p):
            n_html += 1
            print("  [html]  ", os.path.relpath(p, target))
    for p in glob.glob(os.path.join(target, "**", "layers.json"), recursive=True):
        if localize_layers(p):
            n_json += 1
            print("  [json]  ", os.path.relpath(p, target))

    print(f"[localize] 完成：改了 {n_html} 个 HTML、{n_json} 个 layers.json → {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
