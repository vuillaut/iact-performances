# Find records

`Database.query` returns the records that match every criterion you give.
Without criteria it returns all records except the superseded ones.

## Filter by header fields

These keyword filters compare a header field by equality: `quantity`,
`definition`, `energy_integration`, `energy_type`, `instrument`,
`configuration`, `analysis`, `data_kind`, `crab_reference`.

```python
import iact_perf

db = iact_perf.load()

recs = db.query(instrument="magic", quantity="angular_resolution")
for rec in recs:
    print(rec.id, rec.meta.definition)
```

A list means "any of":

```python
recs = db.query(instrument=["magic", "lst1"], quantity="sensitivity")
print(len(recs))
```

An unknown filter name raises a `TypeError` that lists the allowed names, so
a typo does not silently return everything.

## Filter by zenith and observation time

`zenith` keeps the records whose zenith range contains the angle. Records with
an unknown zenith range are dropped, since nothing says they match.

```python
recs = db.query(quantity="sensitivity", zenith="20 deg", observation_time="50 h")
for rec in recs:
    print(rec.source, rec.meta.conditions.zenith_range)
```

Both accept a string with a unit or an astropy `Quantity`:
`zenith=20 * u.deg` works as well.

## Filter on anything else

`where` takes a function of the record. Use it for the conditions that have
no keyword, such as the Moon or the offset:

```python
dark = db.query(
    instrument="ctao",
    analysis="prod6-official",
    quantity="sensitivity",
    where=lambda r: r.meta.conditions.moon == "dark",
)
print(len(dark))
```

## Restrict to one source

```python
recs = db.query(source="magic_aleksic2016_performance-upgrade", quantity="sensitivity")
print(len(recs))
```

If you know the record id, `get` returns it directly, and raises `KeyError`
if it does not exist:

```python
rec = db.get(
    "magic_aleksic2016_performance-upgrade",
    "sensitivity_differential_excess-over-sqrt-bkg_crab_zd00-30",
)
```

## Include superseded sources

Records of a source that a newer one replaces are left out by default. Ask
for them with `include_superseded=True`, and check each record with
`db.is_superseded(rec)`.

```python
everything = db.query(include_superseded=True)
old = [r for r in everything if db.is_superseded(r)]
```

## Browse

`summary` makes one row per record, as an astropy `Table`. It is the quickest
way to see what a query returned:

```python
db.summary(db.query(instrument="magic", quantity="sensitivity")).pprint(max_width=-1)
```

To see what values the filters accept, list the identifiers:

```python
print(sorted(db.instruments))
print(sorted(db.analyses))
print([c.id for c in db.instruments["ctao"].configurations])
```

The same listing is available from the shell:

```bash
iact-perf list --instrument magic --quantity sensitivity
```
