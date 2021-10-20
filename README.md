# XCDAT Validation and Tutorials

This repository explores the capabilities of [xarray](https://github.com/pydata/xarray) and [XCDAT](https://github.com/XCDAT/xcdat) for climate data analysis. It consists of Jupyter Notebooks for tutorials and the validation of a subset of [CDAT](https://github.com/CDAT/cdat) functions replicated using xarray/XCDAT.

## Getting Started

### Directory Layout

- `scripts/` stores utility scripts (e.g., the PCMDI xml reader that Steve wrote)
- `tutorials/` stores tutorials on how to use xarray and XCDAT -- may be moved to the official XCDAT docs in the future
- `validation/` stores CDAT vs. xarray/XCDAT comparison notebooks
 
### Setup

1. Clone this repo

   ```bash
   git clone https://github.com/XCDAT/xcdat_test
   ```

2. Create and activate the XCDAT Anaconda test environment

   ```bash
   cd xcdat_test
   conda env create -f conda-env/test.yml
   conda activate xcdat_test
   ```

3. Start working with the Jupyter Notebooks!

### Demo input preparation

[Sample PMP download data for demos](https://github.com/PCMDI/pcmdi_metrics/blob/master/doc/jupyter/Demo/Demo_0_download_data.ipynb)

```bash
wget https://raw.githubusercontent.com/PCMDI/pcmdi_metrics/master/doc/jupyter/Demo/Demo_0_download_data.ipynb
```

## FYI: Useful External Resources

- [XCDAT Docs](https://xcdat.readthedocs.com)
- [Xarray Docs](https://xarray.pydata.org/en/stable/index.html)
- Xarray usage examples

  - [A Quick Introduction to CMIP6](https://towardsdatascience.com/a-quick-introduction-to-cmip6-e017127a49d3)
  - [Creating a subset of dataset using Xarray](https://www.nccs.nasa.gov/nccs-users/instructional/adapt-instructional/python/xarray-monthly-climatology)
  - [Xarray Access CMIP5 Data (NCI data training)](https://nci-data-training.readthedocs.io/en/latest/_notebook/climate/1_01_Xarray_access_CMIP5.html)
  - [Visualize Climate data with Python](https://nordicesmhub.github.io/climate-data-tutorial/03-visualization-python/)

- Visualization examples

  - [Hawkins Warming Stripes](https://towardsdatascience.com/climate-heatmaps-made-easy-6ec5be0be6ff)
  - [Map using proplot](https://towardsdatascience.com/a-quick-introduction-to-cmip6-e017127a49d3)
  - [Map using cartopy](https://nordicesmhub.github.io/climate-data-tutorial/03-visualization-python/)
