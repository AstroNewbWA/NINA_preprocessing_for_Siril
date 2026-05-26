import sirilpy as s

s.ensure_installed("astropy")
from astropy.io import fits

s.ensure_installed("itertools")
from itertools import product

import glob
import os
import re
import shutil
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

siril = s.SirilInterface()
try:
   siril.connect()
   print("Connected successfully!")
except SirilConnectionError as e:
   print(f"Connection failed: {e}")

doFlats = False
doLights = True
   
cwd = os.getcwd()
# fixme verify in right directory

if doFlats:

    if not os.path.isdir("./FLAT"):
        raise Exception(f"can't find a FLAT directory. Is your working directory {cwd} correct?")
    
    siril.cmd("cd", "./FLAT")
    os.chdir("./FLAT") # do i need both???

    # turn all the fits into FitData objects
    allFitData = [] 
    for f in glob.glob('*.fits'):
        hdul = fits.open(f)
        fitdata = FitData(hdul)
        # fixnm check for correct file type?
        allFitData.append(fitdata)

    if len(allFitData) < 2:
        raise Exception(f"can't find enough fit files in the flats directory?")

    # get a list of all the unique filter types in this directory ...
    allFilters = sorted(set([fd.filtertype for fd in allFitData]))
    print(f"found these filters types in the flats: {allFilters}")

    # for each kind of filter ...
    for f in allFilters:
   
        # make a subdirectory and then move all the flats that used this
        # filter into it
        print(f"processing flats for filter {f}")
        uniq = uuid.uuid4()
        temp_dirname = f"{f}flats_{uniq}"
        os.mkdir(temp_dirname)

        f_fitfiles = [fff for fff in allFitData if fff.filtertype == f ]
        if len(f_fitfiles) == 0:
            raise Exception(f"your logic must be broken")

        for fit in f_fitfiles:
            os.link(fit.filename,f"{temp_dirname}/{fit.filename}")

        # change into the subdirectory and turn the files into a sequence
        siril.cmd("cd", temp_dirname)
        os.chdir(temp_dirname) # do i need both???
        filter_flats_seq_name = f"{f}_flats_{uniq}"
        siril.cmd("convert",filter_flats_seq_name)
        print(f"converted flats to sequence {filter_flats_seq_name}")
    
        # calibrate the flat sequence, using a synthetic bias value.
        siril.cmd("calibrate",filter_flats_seq_name,f"-bias={bias_val}")
        calibrated_filter_flats_seq_name = f"pp_{filter_flats_seq_name}"
        print(f"calibrated flats; new sequence is {calibrated_filter_flats_seq_name}")
    
        # stack the flats. output will be in parent directory
        stacked_flat_fname = f"{f}_flat_stacked"
        siril.cmd("stack",calibrated_filter_flats_seq_name,f"rej w 3 3 -nonorm -out=../{stacked_flat_fname}")
        print(f"stacking for {f} flats completed and file copied to parent FLAT directory")
        siril.cmd("cd", "..")
        os.chdir("..") # do i need both???
        
    siril.cmd("cd", "..")
    os.chdir("..") # do i need both???

if doLights:
  
    if not os.path.isdir("./LIGHT"):
        raise Exception("can't find a LIGHT directory. Is your working directory {cwd} correct?")
    
    siril.cmd("cd", "./LIGHT")
    os.chdir("./LIGHT") # i need to do both???? FIXME

    allFitData = [] 
    for f in glob.glob('*.fits'):
        hdul = fits.open(f)
        fitdata = FitData(hdul)
        # fixnm check for correct file type?
        allFitData.append(fitdata)

    # get a list of all the unique object types and filter types in this directory ...
    allObjects = sorted(set([fd.obsobject for fd in allFitData]))
    allFilters = sorted(set([fd.filtertype for fd in allFitData]))
    allCombinations = product(allObjects,allFilters)

    for combo in allCombinations:
        print(combo)

        # get a list of all the fits objects for this combo
        of_fitfiles = [fo for fo in allFitData if fo.obsobject == combo[0] and fo.filtertype == combo[1] ]
        for f in of_fitfiles:
            print(f)
        
        if len(of_fitfiles) < 2 :
            print(f"did not find enough lights with combination {combo[0]} and {combo[1]}; skipping")
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
        #os.chdir(temp_dirname)
        combo_lights_seq_name = temp_dirname
        siril.cmd("convert",combo_lights_seq_name)
        print(f"converted lights for object {combo[0]} and filter {combo[1]} to sequence {combo_lights_seq_name}")
        
        # find the matching filter-specific flat to use with these lights
        matched_flat_name = f"{combo[1]}_flat_stacked.fit"
        matched_flat_path = f"../../FLAT/{matched_flat_name}"
        
        # calibrate the lights, using a synthetic bias value and the stacked filter-specific flat
        siril.cmd("calibrate",combo_lights_seq_name,f"-bias={bias_val} -flat={matched_flat_path}")
        calibrated_combo_lights_seq_name = f"pp_{combo_lights_seq_name}"
        print(f"finished calibrating lights; new sequence is {calibrated_combo_lights_seq_name}")
    
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
        print(f"{stacked_combo_light_fname}")
        siril.cmd("stack",r_bkg_calibrated_combo_lights_seq_name,f"rej w 3 3 -norm=addscale -output_norm -out=../{stacked_combo_light_fname}")
        print(f"stacking for {combo[0]}-{combo[1]} lights completed and file copied to parent LIGHT directory")
        
        siril.cmd("cd", "..")
        ###os.chdir("..") # do i need both???

    siril.cmd("cd", "..")
    os.chdir("..") # do i need both???

    

    




    
