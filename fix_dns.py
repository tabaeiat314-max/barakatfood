path = "docker-compose.yml"

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = """  db:
    dns:
      - 168.63.129.16
    image: postgres:16"""

new = """  db:
    dns:
      - 8.8.8.8
      - 8.8.4.4
    image: postgres:16"""

assert content.count(old) == 1, "anchor not found or not unique"
content = content.replace(old, new)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Patched successfully.")
