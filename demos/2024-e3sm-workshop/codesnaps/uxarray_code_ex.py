# %%
import os

import uxarray as ux

# 1. Open the unstructured grid data.
file_dir = "demos/2024-e3sm-workshop/sample_data/"
grid_path = os.path.join(file_dir, "oQU480.grid.nc")
data_path = os.path.join(file_dir, "oQU480.data.nc")

uxds = ux.open_dataset(grid_path, data_path)

# 2. Visualize the grid topology.
grid = uxds.uxgrid
grid.plot(title="Default Grid Plot Method", height=350, width=700)

# 3. Calculate the total face area.
area = grid.calculate_total_face_area()
# 8.806940123958533

# 4. Visualize data as polygons.
uxds["bottomDepth"].plot(
    title="Default UXDataArray Plot for Face-Centered Data", height=350, width=700
)
