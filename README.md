# xCDAT Validation

This repository is dedicated to xCDAT feature prototyping and validation. It is utilized in conjunction with the pull requests in the main repository [here](https://github.com/xCDAT/xcdat). Validation consists of Python scripts and Jupyter Notebooks, including comparisons of `xarray`/`xcdat` against a subset of [CDAT](https://github.com/CDAT/cdat) functionality via `cdms2`, `cdutil`, and `genutil`.

## Getting Started

### Directory Layout

- `scripts/` stores utility scripts
- `validation/` stores validation scripts and notebooks

### Setup

1. Clone this repo

   ```bash
   git clone https://github.com/xCDAT/xcdat_test
   ```

2. Create and activate a conda environment that includes `xcdat`, `cdms2`, `cdutil`, and `genutil`.

   - Work with the latest stable version of `xcdat` from `conda-forge`

      ```bash
      cd xcdat_test
      conda env create -f conda-env/test_stable.yml
      conda activate xcdat_test_stable
      ```

   - Work with the latest version of `xcdat` on the `main` branch

      ```bash
      cd xcdat_test
      conda env create -f conda-env/test_dev.yml
      conda activate xcdat_test_dev

      # Clone the latest version of xcdat and install into the `xcdat_test_dev` env
      git clone https://github.com/xCDAT/xcdat
      cd xcdat
      python -m pip install .
      ```

3. Start working with the Jupyter Notebooks!

### Demo input preparation

[Sample PMP download data for demos](https://github.com/PCMDI/pcmdi_metrics/blob/master/doc/jupyter/Demo/Demo_0_download_data.ipynb)

```bash
wget https://raw.githubusercontent.com/PCMDI/pcmdi_metrics/master/doc/jupyter/Demo/Demo_0_download_data.ipynb
```

## FYI: Useful External Resources

- [xCDAT Docs](https://xcdat.readthedocs.io)
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
