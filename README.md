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
