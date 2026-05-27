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
        return f"{self.filename} {self.filetype} {self.obsobject} {self.filtertype}"
        
def get_fits(s,seq):
    # if there is a current sequence loaded, return a list of all the included (ie selected) FITS files
    # otherwise, return a list of all the FITs files in the current directory
    if not cur_seq:
        print("no currently loaded sequence; returning a list of all the fits files in the directory")
        ret = []
        for f in glob.glob('*.fits'):
            ret.append(f)
        return ret
    siril.log(f"getting FITs file list from selected files in sequence {cur_seq.seqname}")
    incl_fits =  [os.path.basename(s.get_seq_frame_filename(i)) for i in range(cur_seq.number) if s.get_seq_imgdata(i).incl == 1]
    incl_fits_number = len(incl_fits)
    siril.log(f"returning {incl_fits_number} included fits of {cur_seq.number} total fits in sequence")
    return incl_fits
    
def get_fits_data(fn):
    # for each filename in the list fn, return the associated FitData
    ret = []
    for f in fn:
        hdul = fits.open(f)
        # fixnm check for correct file type?
        ret.append(FitData(hdul))
    return ret


# connect to siril    
siril = s.SirilInterface()
try:
   siril.connect()
   print("Connected successfully!")
except SirilConnectionError as e:
   print(f"Connection failed: {e}")
   
siril.log("NINA_light_preprocessing starting")

# make sure we are in the LIGHT directory
cwd = os.getcwd()
if not os.path.basename(cwd) == "LIGHT":
    siril.error_messagebox(f"Not in the LIGHT directory. Is your working directory {cwd} correct?",False)
    sys.exit(1)

# check for existing stack flats and if not found give user the opportunity to create them first
flatsfound = []
for f in glob.glob('../FLAT/*flat_stacked.fit'):
    flatsfound.append(f)
if len(flatsfound) == 0:
    ret = siril.confirm_messagebox("Proceed without stacked flats?","No existing stacked flats found in FLAT directory. Quit the script and run NINA_flat_preprocessing.py first, or cancel to continue without flats?","Quit the script")
    if ret:
        sys.exit(1)

# if no loaded sequence, give the user the opportunity to do that and cull bad subs first
cur_seq = None
try:
    cur_seq = siril.get_seq()
except s.exceptions.NoSequenceError:
    ret = siril.confirm_messagebox("Proceed without loaded sequence?","No current sequence exists. Loading a sequence of all the lights lets you cull bad subs before processing. (No need to separate them by filter/object; the script will do that.) Quit the script and set the sequence, or cancel to continue wthout a sequence.","Quit the script")
    if ret:
        sys.exit(1)

# get the fit data for all the included fits in the sequence/directory
allFitsFiles = get_fits(siril,cur_seq)
allFitData = get_fits_data(allFitsFiles)

if len(allFitData) < 2:
    siril.error_messagebox(f"can't find enough fit files in the lights directory?")

# get a list of all the unique object types and filter types combinations in this directory ...
allObjects = sorted(set([fd.obsobject for fd in allFitData]))
allFilters = sorted(set([fd.filtertype for fd in allFitData]))
allCombinations = product(allObjects,allFilters)

for combo in allCombinations:
    siril.log(f"processing lights with object {combo[0]} and filter {combo[1]}")

    # get a list of all the fits objects for this combo
    of_fitfiles = [fo for fo in allFitData if fo.obsobject == combo[0] and fo.filtertype == combo[1] ]
    for f in of_fitfiles:
        siril.log(f"{f}")
        
    if len(of_fitfiles) < 2 :
        siril.log(f"did not find enough lights with combination {combo[0]} and {combo[1]} for stacking; skipping")
        continue

    uniq = uuid.uuid4()
    temp_dirname = f"{combo[0]}-{combo[1]}_lights_{uniq}"
    # siril does not like embedded spaces
    temp_dirname = temp_dirname.replace(" ","_")
    os.mkdir(temp_dirname)
    print(f"create subdir {temp_dirname}")
        
    # link the specific lights we're processing into a sub directory
    for fit in of_fitfiles:
        os.link(fit.filename,f"{temp_dirname}/{fit.filename}")
        
    # turn the files into a sequence
    siril.cmd("cd", temp_dirname)
    combo_lights_seq_name = temp_dirname
    siril.cmd("convert",combo_lights_seq_name)
    siril.log(f"converted lights for object {combo[0]} and filter {combo[1]} to sequence {combo_lights_seq_name}")
        
    # find the matching filter-specific flat to use with these lights
    matched_flat_name = f"{combo[1]}_flat_stacked.fit"
    matched_flat_path = f"../../FLAT/{matched_flat_name}"

    # fixme what if no matching flats???
        
    # calibrate the lights, using a synthetic bias value and the stacked filter-specific flat
    siril.cmd("calibrate",combo_lights_seq_name,f"-bias={bias_val} -flat={matched_flat_path}")
    calibrated_combo_lights_seq_name = f"pp_{combo_lights_seq_name}"
    siril.log(f"finished calibrating lights; new sequence is {calibrated_combo_lights_seq_name}")
    
    # extract linear gradient
    #siril.cmd("seqsubsky",calibrated_combo_lights_seq_name,"1")
    #bkg_calibrated_combo_lights_seq_name = f"bkg_{calibrated_combo_lights_seq_name}"
    bkg_calibrated_combo_lights_seq_name = f"{calibrated_combo_lights_seq_name}"

    # align lights
    siril.cmd("register",bkg_calibrated_combo_lights_seq_name)
    r_bkg_calibrated_combo_lights_seq_name = f"r_{bkg_calibrated_combo_lights_seq_name}"
    # catch exception here and tell user to throw out bad subs and retry
    
    # stack the lights. output will be in parent directory
    datestamp = of_fitfiles[0].obsdateloc
    stacked_combo_light_fname = f"{combo[0]}-{combo[1]}_light_{datestamp}_stacked"
    # siril does not like embedded spaces
    stacked_combo_light_fname = stacked_combo_light_fname.replace(" ","_")
    siril.cmd("stack",r_bkg_calibrated_combo_lights_seq_name,f"rej w 3 3 -norm=addscale -output_norm -out=../{stacked_combo_light_fname}")
    print(f"stacking for {combo[0]}-{combo[1]} lights completed and file {stacked_combo_light_fname} copied to parent LIGHT directory")
        
    siril.cmd("cd", "..")
    
siril.log("NINA_light_preprocessing finished")
