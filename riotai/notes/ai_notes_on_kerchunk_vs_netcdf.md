## I/O Comparison

### `open_mfdataset` on raw NetCDFs

- Opens **every NetCDF file**
- Reads **metadata from each file** (dimensions, variables, attributes)
- Builds a global Dask graph after inspecting all files
- Performance dominated by:

  - Number of files
  - Metadata I/O
  - Filesystem latency

### Kerchunk JSON references

- Reads **one small JSON file**
- No NetCDF metadata reads at open time
- Directly maps array chunks → byte ranges in the original files
- Skips file-by-file inspection entirely

---

## Where kerchunk is _much faster_

### 1. **Many small NetCDF files**

Typical CMIP / E3SM case:

- Thousands to tens of thousands of files
- `open_mfdataset` can take **minutes**
- Kerchunk open is usually **seconds**

**Why:**
Kerchunk replaces O(N files) metadata reads with O(1) JSON read.

---

### 2. **Cloud object storage (S3, GCS, Azure)**

Kerchunk is _dramatically_ faster here.

- `open_mfdataset`:

  - Many HEAD/GET requests
  - High latency per file

- Kerchunk:

  - One JSON read
  - Then byte-range reads only when data are actually needed

**Rule of thumb:**
If your data are on object storage, kerchunk is almost always the right choice.

---

### 3. **Lazy, slice-based workflows**

Examples:

- Time subsetting
- Spatial slices
- Diagnostics that touch a subset of variables

Kerchunk:

- Reads **only the chunks you actually touch**
- Avoids opening irrelevant files entirely

---

## Where kerchunk is _not_ necessarily faster

### 1. **Fast parallel filesystems (e.g., Lustre, GPFS)**

On HPC systems:

- Metadata operations are cheap
- `open_mfdataset` can already be fast if:

  - `combine='by_coords'`
  - `parallel=True`
  - Reasonable file counts

In these cases:

- Kerchunk may be only marginally faster
- Or similar once dataset is opened

---

### 2. **Reading _everything_**

If you immediately:

```python
ds.load()
```

Then:

- Total I/O volume dominates
- Kerchunk and raw NetCDF often converge in performance
- Kerchunk still avoids metadata overhead, but bulk reads cost the same

---

### 3. **Poorly chunked source files**

Kerchunk **does not fix bad chunking**.

If NetCDF files:

- Have chunks misaligned with access patterns
- Use compression with tiny chunks

Then kerchunk will faithfully reproduce that inefficiency.

---

## Typical performance comparison (realistic)

| Scenario                 | `open_mfdataset` | Kerchunk        |
| ------------------------ | ---------------- | --------------- |
| Open dataset (10k files) | 1–5 min          | 1–5 sec         |
| Cloud storage            | Slow             | Much faster     |
| Lazy slicing             | Moderate         | Fast            |
| Full `load()`            | Similar          | Similar         |
| HPC Lustre, few files    | Fast             | Slightly faster |

---

## Key gotchas with kerchunk

- **Up-front cost**: You pay once to generate the JSON
- **Storage**: JSONs can be large (10s–100s of MB for big collections)
- **Fragility**: If source files move or change → references break
- **Updates**: Appending new files means regenerating or merging refs

---

## Bottom line (practical guidance)

**Kerchunk is faster than `open_mfdataset` when:**

- You have many files
- You’re on cloud or high-latency storage
- You do lazy, subset-heavy analysis
- You repeatedly open the same dataset

**`open_mfdataset` is fine when:**

- Files live on fast HPC filesystems
- File count is modest
- You don’t want to manage reference files
