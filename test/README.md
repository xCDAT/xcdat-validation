(base) -bash-4.2$ conda create -n xarray_test_20201112
(base) -bash-4.2$ conda activate xarray_test_20201112
(xarray_test_20201112) -bash-4.2$ conda install -c conda-forge xarray dask netCDF4 bottleneck


conda create -y -n cdat_v8.2.1 -c conda-forge -c cdat/label/v8.2.1 cdat "libnetcdf=*=mpi_openmpi_*" "mesalib=17.3.9" "python=3.7"
conda activate cdat_v8.2.1
conda install -c conda-forge xarray 
conda install -c conda-forge netcdf4 
