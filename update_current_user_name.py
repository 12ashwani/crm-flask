from pathlib import Path

patterns = [
    ('{{ current_user.username }}', '{{ current_user.name or current_user.username }}'),
    ('{{ current_user.username[0].upper() }}', '{{ (current_user.name or current_user.username)[0].upper() }}'),
    ('{{ current_user.username[0]|upper }}', '{{ (current_user.name or current_user.username)[0]|upper }}')
]

for p in Path('templates').rglob('*.html'):
    text = p.read_text(encoding='utf-8')
    new = text
    for old, newstr in patterns:
        new = new.replace(old, newstr)
    if new != text:
        p.write_text(new, encoding='utf-8')
        print('updated', p)
