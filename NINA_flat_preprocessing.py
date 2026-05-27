import sirilpy as s

s.ensure_installed("astropy")
from astropy.io import fits

s.ensure_installed("itertools")
from itertools import product

import glob
import os
import re
import shutil
import sys
import time
import uuid

# This is a NINA-friendly, filter-wheel-friendly, Siril preprocessing script.
# 
# It expects to read fit files laid out thusly:
#
#                                 ------------FLAT
#                                |             contains filter-specific flat files, e.g., 2026-05-02_20-23-52_L_7.50_1.50s_0010.fits
#  current working directory  ---| 
#   e.g. 2026-05-02              |
#                                -------------LIGHT
#                                              contains filter-specific light files, e.g., 2026-05-02_23-48-38_L_-0.20_60.00s_0026.fits
#                                              these files can point to varying targets; so there can be a bunch of L, R, G, B files
#                                              with M31 as its OBJECT and also a bunch of S, H, O, files with C27 as its OBJECT
#
# There are two scripts: NINA_flats_preprocessing.py, which should be run out of the FLAT directory, and NINA_lights_preprocessing.py,
# which should be run out of the LIGHT directory.

bias_val = """=64*$OFFSET""" # synthetic bias value for QHY minicam8/IMX 585 mono

class FitData:
    filename = "" # e.g., 2026-05-02_20-23-52_L_7.50_1.50s_0010.fits
    filetype = "" # LIGHT, FLAT etc
    filtertype = "" # L, R ..
    obsobject ="" # M31 ...
    obsdate = "" # 2026-05-02 (as string, in local time)
    exposure = "" # 60.0 (as string, in seconds)
    
    def __init__(self,hdul):
            self.filename = hdul[0].fileinfo()['file'].name
            self.filetype = hdul[0].header['IMAGETYP']
            self.obsobject = hdul[0].header['OBJECT']
            self.filtertype = hdul[0].header['FILTER']
            self.obsdateloc = hdul[0].header['DATE-LOC'][:10]
            self.exposure = hdul[0].header['EXPOSURE']
            # what to fo if not found FIMXE
    def __str__(self):
        return f"{self.filename} {self.filetype} {self.obsobject}"
        
def get_fits(s,seq):
    # if there is a current sequence loaded, return a list of all the included (ie selected) FITS files
    # otherwise, return a list of all the FITs files in the current directory
    if not cur_seq:
        print("no currently loaded sequence; returning a list of all the fits files in the directory")
        ret = []
        for f in glob.glob('*.fits'):
            ret.append(f)
        return ret
    print(f"getting FITs file list from selected files in sequence {cur_seq.seqname}")
    incl_fits =  [os.path.basename(s.get_seq_frame_filename(i)) for i in range(cur_seq.number) if s.get_seq_imgdata(i).incl == 1]
    incl_fits_number = len(incl_fits)
    print(f"returning {incl_fits_number} included fits of {cur_seq.number} total fits in sequence")
    return incl_fits
    
def get_fits_data(fn):
    # for each filename in the list fn, return the associated FitData
    ret = []
    for f in fn:
        hdul = fits.open(f)
        # fixnm check for correct file type?
        ret.append(FitData(hdul))
    return ret

siril.log("NINA_flat_preprocessing starting")

# connect to siril    
siril = s.SirilInterface()
try:
   siril.connect()
   print("Connected successfully!")
except SirilConnectionError as e:
   print(f"Connection failed: {e}")

# make sure we are in the FLAT directory
cwd = os.getcwd()
if not os.path.basename(cwd) == "FLAT":
    siril.error_messagebox(f"Not in the FLAT directory. Is your working directory {cwd} correct?",False)
    sys.exit(1)

# if no loaded sequence, give the user the opportunity to do that and cull bad subs first
try:
    cur_seq = siril.get_seq()
except s.exceptions.NoSequenceError:
    ret = siril.confirm_messagebox("Proceed without sequence?","No current sequence exists. Loading a sequence of all the flats lets you cull bad subs before processing. (No need to separate them by filter; the script will do that.) Quit and set the sequence?","Quit the script, or cancel to continue")
    if ret:
        sys.exit(1)

# get the fit data for all the included fits in the sequence/directory
allFitsFiles = get_fits(siril,cur_seq)
allFitData = get_fits_data(allFitsFiles)

if len(allFitData) < 2:
    siril.error_messagebox(f"can't find enough fit files in the flats directory?")

# get a list of all the unique filter types in this directory ...
allFilters = sorted(set([fd.filtertype for fd in allFitData]))
print(f"found these filters types in the flats: {allFilters}")

# for each kind of filter ...
for f in allFilters:
   
    # make a subdirectory and then move all the flats that used this
    # filter into it
    print(f"processing flats for filter {f}")
    uniq = uuid.uuid4()
    temp_dirname = f"{f}_flats_{uniq}"
    os.mkdir(temp_dirname)

    f_fitfiles = [fff for fff in allFitData if fff.filtertype == f ]
    if len(f_fitfiles) < 2:
        siril.log(f"Not enough flats for filter {f} to stack; skipping")
        continue

    for fit in f_fitfiles:
        os.link(fit.filename,f"{temp_dirname}/{fit.filename}")

    # change into the subdirectory and turn the files into a sequence
    siril.cmd("cd", temp_dirname)
    filter_flats_seq_name = f"{f}_flats_{uniq}"
    siril.cmd("convert",filter_flats_seq_name)
    siril.log(f"converted {f} flats to sequence {filter_flats_seq_name}")
    
    # calibrate the flat sequence, using a synthetic bias value.
    siril.cmd("calibrate",filter_flats_seq_name,f"-bias={bias_val}")
    calibrated_filter_flats_seq_name = f"pp_{filter_flats_seq_name}"
    siril.log(f"calibrated {f} flats; new sequence is {calibrated_filter_flats_seq_name}")
    
    # stack the flats. output will be in parent directory
    stacked_flat_fname = f"{f}_flat_stacked"
    siril.cmd("stack",calibrated_filter_flats_seq_name,f"rej w 3 3 -nonorm -out=../{stacked_flat_fname}")
    siril.log(f"stacking for {f} flats completed and file {stacked_flat_fname} copied to parent FLAT directory")
    siril.cmd("cd", "..")

siril.log("NINA_flat_preprocessing finished")
        

