import pathlib

p = pathlib.Path("static/index.html")
s = p.read_text(encoding="utf-8")

# 1) head：favicon + theme-color
old_head = '<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>66th 参展申请 · 导出后台</title>'
new_head = """<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#f3f1eb">
<link rel="icon" type="image/png" href="/favicon.png">
<link rel="apple-touch-icon" href="/favicon.png">
<title>66th 参展申请 · 导出后台</title>"""
assert old_head in s
s = s.replace(old_head, new_head)

# 2) 顶栏：文字 logo → 品牌图
old_logo = '      <div class="logo">66th 参展申请<small>EXPORT CONSOLE</small></div>'
new_logo = """      <a class="brand-bar" href="/" aria-label="66th &amp; 2nd Ave. Vintage Fashion Market">
        <img src="/brand.png" alt="66th &amp; 2nd Ave. Vintage Fashion Market">
        <span class="brand-tag">导出后台<em>Export Console</em></span>
      </a>"""
assert old_logo in s
s = s.replace(old_logo, new_logo)

# 3) 登录卡：品牌图
old_login = '    <span class="brand">EXPORT CONSOLE</span>'
new_login = '    <img class="login-brand" src="/brand.png" alt="66th &amp; 2nd Ave.">'
assert old_login in s
s = s.replace(old_login, new_login)

# 4) CSS
old_css = """  .logo{font-family:var(--display);font-size:15px;font-weight:700;letter-spacing:.02em}
  .logo small{display:block;font-family:var(--display);font-weight:600;font-size:9px;
    letter-spacing:.2em;text-transform:uppercase;color:var(--muted);margin-top:2px}"""
new_css = """  .brand-bar{display:flex;align-items:center;gap:16px;text-decoration:none}
  .brand-bar img{height:42px;width:auto;display:block}
  .brand-tag{display:flex;flex-direction:column;gap:2px;padding-left:16px;
    border-left:1px solid var(--line);font-size:12.5px;font-weight:600;line-height:1.25;color:var(--ink)}
  .brand-tag em{font-family:var(--display);font-style:normal;font-weight:600;font-size:8.5px;
    letter-spacing:.2em;text-transform:uppercase;color:var(--muted)}"""
assert old_css in s
s = s.replace(old_css, new_css)

old_login_css = """  .login-card .brand{display:inline-block;font-family:var(--display);font-size:9px;font-weight:600;
    letter-spacing:.2em;text-transform:uppercase;color:var(--muted);
    border-bottom:1px solid var(--line);padding-bottom:6px;margin-bottom:22px}"""
new_login_css = """  .login-card .login-brand{height:64px;width:auto;display:block;margin-bottom:26px}"""
assert old_login_css in s
s = s.replace(old_login_css, new_login_css)

p.write_text(s, encoding="utf-8")
print("logo / favicon 已接入")
