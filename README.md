# About

Simple script that export work shifts into ical files from an https://gastroplanner.eu/ instance.

# Usage

Create a `config.toml`:
```
url = "https://time.example.com/my-restaurant/"
email = "bob@example.com"
password = "secretpassword"

[[exports]]
name_filter = "Bob Example"
file_path = "bob.ical"

[[exports]]
name_filter = "Alice Example"
file_path = "alice.ical"
```

```
python gastrounplanner.py config.toml
```

Every entry in the `exports` list will be exported into the configured file path.

The shifts are passed through a filter so that only shifts matching the name filter (regexp search) is exported.

It only export shifts that are since the lasts 7 days until the 30 next. This could be adjusted:
```
python gastrounplanner.py config.toml --since -2 --until 14
```
