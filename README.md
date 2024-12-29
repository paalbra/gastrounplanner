# About

Simple script that creates an ical from an https://gastroplanner.eu/ instance.

# Usage

Create a `config.toml`:
```
url = "https://time.example.com/my-restaurant/"
email = "bob@example.com"
password = "secretpassword"
name_filter = "Bob Example"
```

```
python gastrounplanner.py config.toml
```

This will print an ical of all shifts that matches (regexp search) "Bob Example".

It prints shifts that are since the 7 lasts days until the 30 next. This could be adjusted:
```
python gastrounplanner.py config.toml --since -2 --until 14
```

The ical can be written to file, rather than stdout:
```
python gastrounplanner.py config.toml --output my-cal.ical
```
