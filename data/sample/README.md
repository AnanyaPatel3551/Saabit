# Sample dataset

`amazon_sale_report.csv.gz` is the demo file Saabit loads for "Try sample data".

| | |
| --- | --- |
| Dataset | E-Commerce Sales Dataset (file: `Amazon Sale Report.csv`) |
| Kaggle | https://www.kaggle.com/datasets/thedevastator/unlock-profits-with-e-commerce-sales-data |
| Published on Kaggle by | The Devastator |
| Original source | ANil, https://data.world/anilsharma87 |
| Rows | 128,975 (120,378 unique orders, 31 Mar to 29 Jun 2022) |
| Compressed file | gzip of the original CSV; decompresses byte-for-byte to it |
| SHA-256 of the decompressed CSV | `ac9a366da5f3af418831fa53da9eebfc3b3838803e3774eec97dbcb291441beb` |

## Licence

Kaggle lists the licence as "Other (specified in description)". The description's
licence section says only "See the dataset description for more information", and
the only condition stated anywhere is to credit the original authors. No licence
text explicitly grants or forbids redistribution. Checked on 30 Sep 2026.

## Credit

Data from the "E-Commerce Sales Dataset" by ANil (data.world/anilsharma87),
published on Kaggle by The Devastator.

## Rebuild the .gz from the original CSV

```powershell
backend\.venv\Scripts\python.exe -c "import gzip, pathlib; s = pathlib.Path('data/sample/amazon_sale_report.csv'); f = open(s.with_suffix('.csv.gz'), 'wb'); g = gzip.GzipFile(filename=s.name, mode='wb', fileobj=f, compresslevel=9, mtime=0); g.write(s.read_bytes()); g.close(); f.close()"
```
