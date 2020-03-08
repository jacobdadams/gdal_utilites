from osgeo import gdal
import numpy as np
import os

class RasterChunk:
    '''
    Contains the data and associated metadata (driver, projection, etc) for one chunk of a raster file. This chunk can either be the whole file, a subset of the file, or a buffer subset of the whole file. If it is a buffered subset, any areas of the buffer outside the bounds of the original file are filled with np.nan.
    '''


    def __init__(self):

        #: Rows and cols are dimensions of original area and don't include buffer
        self.rows = 0
        self.cols = 0
        self.buffer = 0
        self.data_type = None
        self.driver = None
        self.bands = 0
        self.transform = None
        self.projection = None
        self.cell_size = None
        self.nodata = None



    def read_chunk(self, dem_path, x_start=0, y_start=0, read_x=0, read_y=0, buffer=0):
        '''
        Read the raster at dem_path. Start from start_x, start_y and read read_x and read_y cols and rows, respectively; if these aren't specified, read the whole file. If buffer is specified, read buffer spaces around the area defined by start_x/start_y by read_x/read_y, filling with nodata if buffer goes beyond the bounds of the raster file.
        '''

        #: Rows = i = y values, cols = j = x values; 0,0 at top left of raster

        file_handle = gdal.Open(dem_path, gdal.GA_ReadOnly)

        #: Set rows/cols to windowed size or the original file's size
        if read_y:
            self.rows = read_y
        else:
            self.rows = file_handle.RasterYSize
        
        if read_x:
            self.cols = read_x
        else:
            self.cols = file_handle.RasterXSize


        self.driver = file_handle.GetDriver()
        self.bands = file_handle.RasterCount
        s_band = file_handle.GetRasterBand(1)

        #: Get source georeference info
        self.transform = file_handle.GetGeoTransform()
        self.projection = file_handle.GetProjection()
        self.cell_size = abs(self.transform[5])  #: Assumes square pixels where height=width
        self.nodata = s_band.GetNoDataValue()  #: Assumes all bands have same nodata
        self.data_type = s_band.DataType


        # data_array calculations
        # Non-edge-case values for data_array
        # we multipy by 2 here to get an overlap on each side of the dimension (ie, buffer <> x values <> buffer)
        x_size = self.cols + 2 * buffer
        y_size = self.rows + 2 * buffer
        x_off = x_start - buffer
        y_off = y_start - buffer

        # Values for ReadAsArray, these aren't changed later unelss the border case
        # checks change them
        read_x_off = x_off
        read_y_off = y_off
        read_x_size = x_size
        read_y_size = y_size

        # Slice values (of data_array) for copying read_array into data_array,
        # these aren't changed later unelss the border case checks change them
        da_x_start = 0
        da_x_end = x_size
        da_y_start = 0
        da_y_end = y_size

        # Edge logic
        # If data_array exceeds bounds of image:
        #   Adjust x/y offset to appropriate place (for < 0 cases only).
        #   Reduce read size by buffer (we're not reading that edge area on one side)
        #   Move start or end value for data_array slice to be -buffer ([:-buffer])
        # Checks both x and y, setting read and slice values for each dimension if
        # needed
        if x_off < 0:
            read_x_off = 0
            read_x_size -= buffer
            da_x_start = buffer
        if x_off + x_size > file_handle.RasterXSize:
            read_x_size -= buffer
            da_x_end = -buffer

        if y_off < 0:
            read_y_off = 0
            read_y_size -= buffer
            da_y_start = buffer
        if y_off + y_size > file_handle.RasterYSize:
            read_y_size -= buffer
            da_y_end = -buffer

        #: Initialize data_array holding superset of actual desired window, initialized to NoData value if present, 0 otherwise.
        #:  Edge case logic insures edges fill appropriate portion when loaded in
        if self.nodata or self.nodata == 0:
            self.data_array = np.full((self.bands, y_size, x_size), self.nodata)
        else:
            data_array = np.full((self.bands, y_size, x_size), 0)

        for band in range(1, self.bands + 1):

            s_band = file_handle.GetRasterBand(band)

            # Master read call. read_ variables have been changed for edge
            # cases if needed
            read_array = s_band.ReadAsArray(read_x_off, read_y_off,
                                            read_x_size, read_y_size)
            
            s_band = None

            # The cells of our NoData-intiliazed data_array corresponding to the
            # read_array are replaced with data from read_array. This changes every
            # value, except for edge cases that leave portions of the data_array
            # as NoData.
            data_array[band, da_y_start:da_y_end, da_x_start:da_x_end] = read_array


        # Close source file handle
        file_handle = None

    def write_chunk(self, out_path):
        '''
        Writes the chunk out_path. If the chunk includes a buffer, only the original area inside the buffer is written (the new file will be the same dimensions as the source).
        '''

        #: If source was a VRT, force output to Geotiff
        if self.driver.LongName == 'Virtual Raster':
            driver = gdal.GetDriverByName('gtiff')
        else:
            driver = self.driver

        if os.path.exists(out_path):
            raise IOError(f'Output file {out_path} already exists.')

        target_filehandle = driver.Create(out_path, self.cols, self.rows, self.bands, self.Datatype, options=['tiled=yes', 'bigtiff=yes'])
        target_filehandle.SetGeoTransform(self.transform)
        target_filehandle.SetProjection(self.projection)

        for band in self.bands:
            t_band = target_filehandle.GetRasterBand(band)
            t_band.SetNoDataValue(self.nodata)
            t_band.WriteArray(self.data_array[band])

        t_band = None
        target_filehandle = None