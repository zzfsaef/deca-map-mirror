#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_saveload.py —— 给 map.html 加一个「选择存档文件夹」按钮，绕开拖放。

原页面只支持把存档文件夹「拖」到左边方框，而且监听的挂载时机很靠后
（要等全部保护区数据加载完才调用 dropzoneActivate()），所以经常拖不进去。

这个补丁在页面里加一个文件夹选择按钮，直接复用页面自己的 loadFileBinary()，
行为与拖放完全一致：只处理文件名以 animal_population_ 开头、
且路径里不含 slots 的文件。

用法:
    python patch_saveload.py --site "D:/game/猎人/site"
可反复执行，不会重复注入。
"""

import argparse
import os
import sys

MARK = "<!-- SAVE-PICKER-PATCH -->"

SNIPPET = MARK + """
<div id="spb" style="padding:6px 8px;background:#e8eefc;border-bottom:1px solid #9ab;">
  <button id="spb_btn" style="padding:5px 12px;cursor:pointer;font-size:13px;">&#128194; 选择存档文件夹</button>
  <span id="spb_msg" style="margin-left:10px;font-size:12px;color:#334;">未选择</span>
</div>
<input type="file" id="spb_input" webkitdirectory directory multiple style="display:none">
<script>
(function () {
  var bar = document.getElementById('spb');
  var ctrl = document.getElementById('control');
  if (bar && ctrl) ctrl.insertBefore(bar, ctrl.firstChild);

  var inp = document.getElementById('spb_input');
  var msg = document.getElementById('spb_msg');
  document.getElementById('spb_btn').addEventListener('click', function () { inp.click(); });

  inp.addEventListener('change', function () {
    var files = Array.prototype.slice.call(inp.files);
    var used = 0, ignored = 0;
    files.forEach(function (f) {
      var rel = f.webkitRelativePath || f.name;
      if (f.name.indexOf('animal_population_') === 0 && rel.indexOf('slots') < 0) {
        used++;
        loadFileBinary(f);
      } else {
        ignored++;
      }
    });
    msg.textContent = '已读取 ' + used + ' 个种群文件，忽略 ' + ignored + ' 个';
    setTimeout(function () {
      var nav = document.getElementById('pop_nav');
      if (nav) {
        msg.innerHTML = '&#10004; 载入成功，左侧已生成种群列表';
      } else {
        msg.innerHTML = '&#10060; 没生成种群列表 —— 按 F12 看 Console 的红色报错';
      }
    }, 2000);
  });
})();
</script>
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="给 map.html 注入「选择存档文件夹」按钮")
    ap.add_argument("--site", default="site", help="镜像目录")
    ap.add_argument("--restore", action="store_true", help="移除补丁")
    a = ap.parse_args(argv)

    path = os.path.join(a.site, "deca", "hp", "map.html")
    if not os.path.isfile(path):
        print(f"[patch] 找不到 {path}", file=sys.stderr)
        return 1

    with open(path, encoding="utf-8") as f:
        t = f.read()

    if a.restore:
        if MARK in t:
            i = t.index(MARK)
            j = t.index("</script>", i) + len("</script>")
            with open(path, "w", encoding="utf-8") as f:
                f.write(t[:i] + t[j:])
            print("[patch] 已移除补丁")
        else:
            print("[patch] 没有找到补丁，无需处理")
        return 0

    if MARK in t:
        print("[patch] 已经有补丁了，跳过（不重复注入）")
        return 0

    if "</body>" not in t:
        print("[patch] map.html 里没有 </body>，结构不符，放弃", file=sys.stderr)
        return 1

    t = t.replace("</body>", SNIPPET + "\n</body>", 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(t)
    print(f"[patch] 已注入按钮 → {path}")
    print("[patch] 刷新浏览器页面即可看到「选择存档文件夹」按钮")
    return 0


if __name__ == "__main__":
    sys.exit(main())
