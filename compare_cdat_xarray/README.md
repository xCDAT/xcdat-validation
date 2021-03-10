# Compare CDAT and Xarray

Check consistency in results from Xarray and CDAT

## Testing Env

```bash
conda create -y -n cdat_v8.2.1 -c conda-forge -c cdat/label/v8.2.1 cdat "libnetcdf=*=mpi_openmpi_*" "mesalib=17.3.9" "python=3.7"
conda activate cdat_v8.2.1
conda install -c conda-forge xarray 
conda install -c conda-forge netcdf4 
```

## Demo input preparation
[PMP download data for prepare demos](https://github.com/PCMDI/pcmdi_metrics/blob/master/doc/jupyter/Demo/Demo_0_download_data.ipynb)
```bash
conda install -c anaconda wget  ## If you don't have wget in your env
wget https://raw.githubusercontent.com/PCMDI/pcmdi_metrics/master/doc/jupyter/Demo/Demo_0_download_data.ipynb
```
