"""
Make Amber topology files from Gromacs
"""

# ##############################################################################
#                           GPLv3 LICENSE INFO                                 #
#                                                                              #
#  Copyright (C) 2020  Mario S. Valdes-Tresanco and Mario E. Valdes-Tresanco   #
#  Copyright (C) 2014  Jason Swails, Bill Miller III, and Dwight McGee         #
#                                                                              #
#   Project: https://github.com/Valdes-Tresanco-MS/GMX-MMGBSA                  #
#                                                                              #
#   This program is free software; you can redistribute it and/or modify it    #
#  under the terms of the GNU General Public License version 3 as published    #
#  by the Free Software Foundation.                                            #
#                                                                              #
#  This program is distributed in the hope that it will be useful, but         #
#  WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY  #
#  or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License    #
#  for more details.                                                           #
# ##############################################################################

import re
import os
import parmed
import warnings
from GMXMMPBSA.exceptions import *
from GMXMMPBSA.findprogs import find_progs
import subprocess
from math import sqrt

ff_list = {'amber03': 'oldff/leaprc.ff03', 'amber99': 'oldff/leaprc.ff99', 'amber99sb': 'oldff/leaprc.ff99SB',
           'amber99sb-ildn': 'oldff/leaprc.ffSBildn', 'amber94': 'oldff/leaprc.ff94', 'amber96': 'oldff/leaprc.ff96',
           'amber14sb': 'leaprc.protein.ff14SB'}
lig_ff = ['gaff', 'gaff2']

std_aa = ['ALA', 'ARG', 'ASN', 'ASP', 'CYS', 'CYX', 'GLN', 'GLU', 'GLY', 'HID', 'HIE', 'HIP', 'ILE', 'LEU', 'LYS',
          'MET', 'PHE', 'PRO', 'SER', 'THR', 'TRP', 'TYR', 'VAL', 'HIS']

def dist(coor1, coor2):
    return sqrt((coor2[0] - coor1[0]) ** 2 + (coor2[1] - coor1[1]) ** 2 + (coor2[2] - coor1[2]) ** 2)

class CheckMakeTop:
    def __init__(self, FILES, INPUT):
        self.FILES = FILES
        self.INPUT = INPUT
        self.external_progs = find_progs(self.INPUT)
        self.log = open('make_top.log', 'a')
        self.use_temp = False
        self.print_residues = self.INPUT['print_res'].split()[0] == 'within'  # FIXME: this is pretty ugly
        self.within = 4
        if self.print_residues:
            self.within = float(self.INPUT['print_res'].split()[1])

        self.ligand_tpr = None
        self.ligand_mol2 = None

        # create the * prmtop variables for compatibility with the original code
        self.complex_pmrtop = 'COM.prmtop'
        self.receptor_pmrtop = 'REC.prmtop'
        self.ligand_pmrtop = 'LIG.prmtop'

        self.mutant_complex_pmrtop = 'MUT_COM.prmtop'
        self.mutant_receptor_pmrtop = 'MUT_REC.prmtop'
        self.mutant_ligand_pmrtop = 'MUT_LIG.prmtop'

        self.complex_pdb = self.FILES.prefix + 'COM.pdb'
        self.receptor_pdb = self.FILES.prefix + 'REC.pdb'
        self.ligand_pdb = self.FILES.prefix + 'LIG.pdb'
        self.complex_pdb_fixed = self.FILES.prefix + 'COM_FIXED.pdb'
        self.receptor_pdb_fixed = self.FILES.prefix + 'REC_FIXED.pdb'
        self.ligand_pdb_fixed = self.FILES.prefix + 'LIG_FIXED.pdb'

        self.mutant_complex_pdb = self.FILES.prefix + 'MUT_COM.pdb'
        self.mutant_receptor_pdb = self.FILES.prefix + 'MUT_REC.pdb'
        self.mutant_ligand_pdb = self.FILES.prefix + 'MUT_LIG.pdb'
        self.mutant_complex_pdb_fixed = self.FILES.prefix + 'MUT_COM_FIXED.pdb'
        self.mutant_receptor_pdb_fixed = self.FILES.prefix + 'MUT_REC_FIXED.pdb'
        self.mutant_ligand_pdb_fixed = self.FILES.prefix + 'MUT_LIG_FIXED.pdb'
        # self.default_ff = 'leaprc.protein.ff14SB'

        self.getPDBfromTpr()
        self.checkPDB()

    def getPDBfromTpr(self):
        """
        Get PDB file to make topology
        :return:
        """
        gmx = self.external_progs['gmx'].full_path
        # wt complex
        # make index for extract pdb structure
        rec_group, lig_group = self.FILES.complex_groups
        print('Normal Complex: Save group {}_{} in {} (gromacs index) file as {}'.format(rec_group, lig_group,
                                                                                           self.FILES.complex_index,
                                                                                           self.complex_pdb))
        # merge both (rec and lig) groups into complex group, modify index and create a copy
        # 1-rename groups, 2-merge
        c1 = subprocess.Popen(['echo', 'name {r} GMXMMPBSA_REC\n name {l} GMXMMPBSA_LIG\n  {r} | {l}\n'
                                       ' q\n'.format(r=rec_group, l=lig_group)], stdout=subprocess.PIPE)
        # FIXME: overwrite the user index file???
        com_ndx = self.FILES.prefix + 'COM_index.ndx'

        c2 = subprocess.Popen([gmx, "make_ndx", '-n', self.FILES.complex_index, '-o', com_ndx],
                              stdin=c1.stdout, stdout=self.log, stderr=self.log)
        if c2.wait():  # if it quits with return code != 0
            raise MMPBSA_Error('%s failed when querying %s' % (gmx + 'make_ndx', self.FILES.receptor_tpr))
        self.FILES.complex_index = com_ndx

        c3 = subprocess.Popen(['echo', 'GMXMMPBSA_REC_GMXMMPBSA_LIG'], stdout=subprocess.PIPE)
        # we get only first trajectory to extract a pdb file and make amber topology for complex
        c4 = subprocess.Popen([gmx, "trjconv", '-f', self.FILES.complex_trajs[0], '-s', self.FILES.complex_tpr,
                               '-o', self.complex_pdb, '-n', self.FILES.complex_index, '-b', '0', '-e', '0'],
                              stdin=c3.stdout, stdout=self.log, stderr=self.log)
        if c4.wait():  # if it quits with return code != 0
            raise MMPBSA_Error('%s failed when querying %s' % (gmx + 'trjconv', self.FILES.complex_tpr))

        # clear trajectory
        if self.FILES.solvated_traj:
            print('Clear normal complex trajectories...')
            new_trajs = []
            for i in range(len(self.FILES.complex_trajs)):
                c5 = subprocess.Popen(['echo', 'GMXMMPBSA_REC_GMXMMPBSA_LIG'], stdout=subprocess.PIPE)
                # we get only first trajectory to extract a pdb file and make amber topology for complex
                c6 = subprocess.Popen([gmx, "trjconv", '-f', self.FILES.complex_trajs[0], '-s', self.FILES.complex_tpr,
                                       '-o', 'COM_traj_{}.xtc'.format(i), '-n',
                                       self.FILES.complex_index], # FIXME: start and end frames???
                                      stdin=c5.stdout, stdout=self.log, stderr=self.log)
                if c6.wait():  # if it quits with return code != 0
                    raise MMPBSA_Error('%s failed when querying %s' % (gmx + 'trjconv', self.FILES.complex_tpr))
                new_trajs.append('COM_traj_{}.xtc'.format(i))
            self.FILES.complex_trajs = new_trajs

        # Put receptor and ligand (explicitly defined) to avoid overwrite them
        # check if ligand is not protein. In any case, non-protein ligand always most be processed
        if self.FILES.ligand_mol2:
            lig_name = os.path.splitext(os.path.split(self.FILES.ligand_mol2)[1])[0]
            self.ligand_frcmod = self.FILES.prefix + lig_name + '.frcmod'
            # run parmchk2
            l3 = subprocess.Popen(['parmchk2', '-i', self.FILES.ligand_mol2, '-f', 'mol2', '-o', self.ligand_frcmod],
                                  stdout=self.log, stderr=self.log)
            if l3.wait():
                raise MMPBSA_Error('%s failed when querying %s' % ('parmchk2', self.FILES.ligand_mol2))

        # make a temp receptor pdb (even when stability) if decomp to get correct receptor residues from complex. This
        # avoid get multiples molecules from complex.split()
        if self.INPUT['decomprun'] and self.print_residues:
            if self.FILES.stability:
                self.use_temp = True
                cp1 = subprocess.Popen(['echo', '{}'.format(rec_group)], stdout=subprocess.PIPE)
                # we get only first trajectory to extract a pdb file for make amber topology
                cp2 = subprocess.Popen(
                    [gmx, "trjconv", '-f', self.FILES.complex_trajs[0], '-s', self.FILES.complex_tpr, '-o',
                     'rec_temp.pdb', '-n', self.FILES.complex_index, '-b', '0', '-e', '0'],
                    stdin=cp1.stdout, stdout=self.log, stderr=self.log)
                if cp2.wait():  # if it quits with return code != 0
                    raise MMPBSA_Error('%s failed when querying %s' % (gmx + 'make_ndx', self.FILES.complex_tpr))

        # check if stability
        if self.FILES.stability:
            if (self.FILES.receptor_tpr or self.FILES.ligand_tpr):
                warnings.warn(
                    'When Stability calculation mode is selected receptor and ligand are not needed. However, '
                    'the receptor and/or the ligand are defined, so we will ignore them.', StabilityWarning)
            if self.INPUT['alarun'] and (self.FILES.mutant_receptor_tpr or self.FILES.mutant_ligand_tpr):
                warnings.warn(
                    'When Stability calculation mode is selected mutant receptor and/or mutant ligand are not '
                    'needed. However, the receptor or the ligand (mutant) are defined, so we will ignore them.',
                    StabilityWarning)
            return

        # wt receptor
        if self.FILES.receptor_tpr:
            print('Normal receptor: Save group {} in {} (gromacs index) file as {}'.format(self.FILES.receptor_group,
                                                                          self.FILES.receptor_index,
                                                                          self.receptor_pdb))
            p1 = subprocess.Popen(['echo', '{}'.format(self.FILES.receptor_group)], stdout=subprocess.PIPE)
            # we get only first trajectory to extract a pdb file for make amber topology
            cp2 = subprocess.Popen([gmx, "trjconv", '-f', self.FILES.receptor_trajs[0], '-s', self.FILES.receptor_tpr,
                                    '-o', self.receptor_pdb, '-n', self.FILES.receptor_index, '-b', '0', '-e', '0'],
                                   stdin=p1.stdout, stdout=self.log, stderr=self.log)
            if cp2.wait():  # if it quits with return code != 0
                raise MMPBSA_Error('%s failed when querying %s' % (gmx + 'make_ndx', self.FILES.receptor_tpr))
            # clear trajectory
            if self.FILES.solvated_traj:
                print('Clear normal receptor trajectories...')
                new_trajs = []
                for i in range(len(self.FILES.receptor_trajs)):
                    c5 = subprocess.Popen(['echo', '{}'.format(self.FILES.receptor_group)], stdout=subprocess.PIPE)
                    # we get only first trajectory to extract a pdb file and make amber topology for complex
                    c6 = subprocess.Popen(
                        [gmx, "trjconv", '-f', self.FILES.receptor_trajs[0], '-s', self.FILES.receptor_tpr,
                         '-o', 'REC_traj_{}.xtc'.format(i), '-n',
                         self.FILES.receptor_index],  # FIXME: start and end frames???
                        stdin=c5.stdout, stdout=self.log, stderr=self.log)
                    if c6.wait():  # if it quits with return code != 0
                        raise MMPBSA_Error('%s failed when querying %s' % (gmx + 'trjconv', self.FILES.receptor_tpr))
                    new_trajs.append('REC_traj_{}.xtc'.format(i))
                self.FILES.receptor_trajs = new_trajs
        else:
            print('Using receptor structure from complex to make amber topology')
            # wt complex receptor
            print('Normal Complex: Save group {} in {} (gromacs index) file as {}'.format(rec_group,
                                                                                     self.FILES.complex_index,
                                                                                   self.receptor_pdb))
            cp1 = subprocess.Popen(['echo', '{}'.format(rec_group)], stdout=subprocess.PIPE)
            # we get only first trajectory to extract a pdb file for make amber topology
            cp2 = subprocess.Popen(
                [gmx, "trjconv", '-f', self.FILES.complex_trajs[0], '-s', self.FILES.complex_tpr, '-o',
                 self.receptor_pdb, '-n', self.FILES.complex_index, '-b', '0', '-e', '0'],
                stdin=cp1.stdout, stdout=self.log, stderr=self.log)
            if cp2.wait():  # if it quits with return code != 0
                raise MMPBSA_Error('%s failed when querying %s' % (gmx + 'make_ndx', self.FILES.complex_tpr))

        # ligand
        # # check consistence
        if self.FILES.ligand_tpr:  # ligand is protein
            # wt ligand
            l1 = subprocess.Popen(['echo', '{}'.format(self.FILES.ligand_group)], stdout=subprocess.PIPE)
            # we get only first trajectory for extract a pdb file for make amber topology
            l2 = subprocess.Popen([gmx, "trjconv", '-f', self.FILES.ligand_trajs[0], '-s',
                                   self.FILES.ligand_tpr, '-o', self.ligand_pdb, '-b', '0', '-e', '0'],
                                  stdin=l1.stdout, stdout=self.log, stderr=self.log)
            if l2.wait():  # if it quits with return code != 0
                raise MMPBSA_Error('%s failed when querying %s' % (gmx + 'make_ndx', self.FILES.ligand_tpr))

            # clear trajectory
            if self.FILES.solvated_traj:
                print('Clear normal ligand trajectories...')
                new_trajs = []
                for i in range(len(self.FILES.ligand_trajs)):
                    c5 = subprocess.Popen(['echo', '{}'.format(self.FILES.ligand_group)], stdout=subprocess.PIPE)
                    # we get only first trajectory to extract a pdb file and make amber topology for complex
                    c6 = subprocess.Popen(
                        [gmx, "trjconv", '-f', self.FILES.ligand_trajs[0], '-s', self.FILES.ligand_tpr,
                         '-o', 'LIG_traj_{}.xtc'.format(i), '-n',
                         self.FILES.ligand_index],  # FIXME: start and end frames???
                        stdin=c5.stdout, stdout=self.log, stderr=self.log)
                    if c6.wait():  # if it quits with return code != 0
                        raise MMPBSA_Error(
                            '%s failed when querying %s' % (gmx + 'trjconv', self.FILES.ligand_tpr))
                    new_trajs.append('LIG_traj_{}.xtc'.format(i))
                self.FILES.ligand_trajs = new_trajs
        else:
            # wt complex ligand
            print('Using ligand structure from complex to make amber topology')
            print('Save group {} in {} (gromacs index) file as {}'.format(lig_group, self.FILES.complex_index,
                                                                          self.ligand_pdb))
            cl1 = subprocess.Popen(['echo', '{}'.format(lig_group)], stdout=subprocess.PIPE)
            # we get only  first trajectory to extract a pdb file for make amber topology
            cl2 = subprocess.Popen([gmx, "trjconv", '-f', self.FILES.complex_trajs[0], '-s', self.FILES.complex_tpr,
                                    '-o', self.ligand_pdb, '-n', self.FILES.complex_index, '-b', '0', '-e', '0'],
                                   stdin=cl1.stdout, stdout=self.log, stderr=self.log)
            if cl2.wait():  # if it quits with return code != 0
                raise MMPBSA_Error('%s failed when querying %s' % (gmx + 'make_ndx', self.FILES.complex_tpr))

    def checkPDB(self):
        """
        Get parmed structure object for complex, receptor and ligand if is protein-like

        1 - Rename HIS
        2 - Rename CYS
        3 - Delete H
        4 - Rename oxygen in termini from GROMACS to AMBER name
          - Rename CD in ILE from GROMACS to AMBER name
        5 - Save
        :return:
        """
        self.complex_str = parmed.read_PDB(self.complex_pdb)  # can always be initialized
        # fix complex structure and save
        self.properHIS(self.complex_str)
        self.properCYS(self.complex_str)
        # For some reason removing the hydrogens returns the hydrogen-bound atoms to their original names. This is
        # problematic with ILE switching from CD to CD1. parmed bug?
        self.complex_str.strip('@/H')
        self.properATOMS(self.complex_str)
        self.complex_str.save(self.complex_pdb_fixed, 'pdb', True)

        if self.INPUT['alarun']:
            self.mutant_complex_str = parmed.read_PDB(self.complex_pdb_fixed)
            # make mutation and save
            self.mutatexala(self.mutant_complex_str)
            self.mutant_complex_str.save(self.mutant_complex_pdb_fixed, 'pdb', overwrite=True)

        if not self.FILES.stability:
            self.receptor_str = parmed.read_PDB(self.receptor_pdb)
            # fix receptor structure
            self.properHIS(self.receptor_str)
            self.properCYS(self.receptor_str)
            self.receptor_str.strip('@/H')
            self.properATOMS(self.receptor_str)
            self.receptor_str.save(self.receptor_pdb_fixed, 'pdb', True)

            # fix ligand structure
            # if self.ligand_isProt and not self.ligand_tpr:  # ligand from complex
                # check if ligand (from complex structure) is really protein-like.
            self.ligand_str = parmed.read_PDB(self.ligand_pdb)
                # for res in self.ligand_str.residues:
                #     if res.name not in std_aa:
                #         self.ligand_isProt = False
                #         raise MMPBSA_Error(
                #             'It appears that the ligand that defined based on complex is non-protein type. '
                #             'This ligand type requires a structure (mol2) and a parameter (frcmod) files. '
                #             'Please define these parameters to perform the calculation correctly.')

            # fix ligand structure if is protein
            self.properHIS(self.ligand_str)
            self.properCYS(self.ligand_str)
            self.ligand_str.strip('@/H')
            self.properATOMS(self.ligand_str)
            self.ligand_str.save(self.ligand_pdb_fixed, 'pdb', True)

            if self.INPUT['alarun']:
                if self.INPUT['mutant'].lower() in ['rec', 'receptor']:
                    self.mutant_receptor_str = parmed.read_PDB(self.receptor_pdb_fixed)
                    # fix mutant receptor structure
                    self.mutatexala(self.mutant_receptor_str)
                    self.mutant_receptor_str.save(self.mutant_receptor_pdb_fixed, 'pdb', True)

                else:
                    if self.FILES.ligand_mol2:
                        raise MMPBSA_Error('Mutation is only possible if the ligand is protein-like')
                    self.mutant_ligand_str = parmed.read_PDB(self.ligand_pdb_fixed)
                    self.mutatexala(self.mutant_ligand_str)
                    self.mutant_ligand_str.save(self.mutant_ligand_pdb_fixed, 'pdb', True)

        # Get residue form receptor-ligand interface
        if self.print_residues:
            if self.use_temp:
                temp_str = parmed.read_PDB('rec_temp.pdb')
                rec_resnum = len(temp_str.residues)
            else:
                rec_resnum = len(self.receptor_str.residues)
            res_list = []
            res_ndx = 1
            for rres in self.complex_str.residues[:rec_resnum]:  # iterate over receptor residues
                lres_ndx = rec_resnum + 1
                for lres in self.complex_str.residues[rec_resnum:]:  # iterate over ligand residues
                    for rat in rres.atoms:
                        rat_coor = [rat.xx, rat.xy, rat.xz]
                        for lat in lres.atoms:
                            lat_coor = [lat.xx, lat.xy, lat.xz]
                            if dist(rat_coor, lat_coor) <= self.within:
                                if res_ndx not in res_list:
                                    res_list.append(res_ndx)
                                    # print(self.within, rres.name, res_ndx, lres.name, lres_ndx, dist(rat_coor,
                                    #                                                                    lat_coor))
                                if lres_ndx not in res_list:
                                    res_list.append(lres_ndx)
                                break
                    lres_ndx += 1
                res_ndx += 1
            res_list.sort()
            self.INPUT['print_res'] = ','.join([str(x) for x in res_list])

    def mutatexala(self, structure):
        idx = 0
        found = False
        if not self.INPUT['mutant_res']:
            raise MMPBSA_Error("No residue for mutation was defined")
        chain, resnum = self.INPUT['mutant_res'].split(':')

        if not chain or not resnum:
            raise MMPBSA_Error("No residue was defined")
        for res in structure.residues:
            if res.number == int(resnum) and res.chain == chain:
                found = True
                break
            idx += 1
        if found:
            structure.residues[idx].name = 'ALA'
            excluded_mask = ':{} &!@CB,C,CA,N,O'.format(idx + 1)
            structure.strip(excluded_mask)
        else:
            raise MMPBSA_Error('Residue {}:{} not found'.format(chain, resnum))

    def properATOMS(self, structure):
        """
        Rename oxygen in termini from GROMACS to AMBER name
        OC1 -> 'O  '
        OC2 -> OXT
        Rename CD in ILE from GROMACS to AMBER name
        CD   ILE -> CD1 ILE
        :return:
        """
        for residue in structure.residues:
            if residue.name == 'ILE':
                for atom in residue.atoms:
                    if atom.name == 'CD':
                        atom.name = 'CD1'

            for atom in residue.atoms:
                if atom.name == 'OC1':
                    atom.name = 'O  '
                elif atom.name == 'OC2':
                    atom.name = 'OXT'

    def properHIS(self, structure):
        """
        Compatible amber name for Histidines from protonation state
        """
        his = ['HIS', 'HIE', 'HID', 'HIP']

        for residue in structure.residues:
            if residue.name in his:
                atoms = [atom.name for atom in residue.atoms if atom.atomic_number == 1]
                if 'HD1' in atoms and 'HE2' in atoms:
                    residue.name = 'HIP'
                elif 'HD1' in atoms:
                    residue.name = 'HID'
                elif 'HE2' in atoms:
                    residue.name = 'HIE'

    def properCYS(self, structure):
        """
        Rename the cys that form a disulfide bond
        :return:
        """
        cys_name = ['CYS', 'CYX', 'CYM']
        allcys = [residue for residue in structure.residues if residue.name in cys_name]
        # print(llcys
        xcys = []
        for residue in allcys:
            for atom in residue.atoms:
                if 'SG' in atom.name:
                    for bondedatm in atom.bond_partners:
                        # exclude CB
                        if bondedatm.residue == residue:
                            continue
                        else:
                            # check if is bonded to cys residue
                            # TODO: Check if bonded atom is SG. Is really necessary?
                            if bondedatm.residue.name in cys_name:
                                if residue not in xcys:
                                    xcys.append(residue)
                                if bondedatm.residue not in xcys:
                                    xcys.append(bondedatm.residue)
        for cys in xcys:
            cys.name = 'CYX'

    def checkForceField(self):
        if self.FILES.protein_ff not in ff_list:
            raise ValueError('This forcefield {} does not match any of the allowed '
                             '({})'.format(self.FILES.protein_ff, ', '.join([x for x in ff_list])))
        if self.FILES.ligand_mol2 and self.FILES.ligand_ff not in lig_ff:
            raise ValueError('This forcefield {} does not match any of the allowed '
                             '({})'.format(self.FILES.ligand_ff, ', '.join([x for x in ff_list])))

    def makeToptleap(self):
        self.checkForceField()
        with open(self.FILES.prefix + 'leap.in', 'w') as tif:
            tif.write('source {}\n'.format(ff_list[self.FILES.protein_ff]))
            tif.write('source leaprc.DNA.bsc1\n')
            tif.write('source leaprc.RNA.OL3\n')
            tif.write('source leaprc.{}\n'.format(self.FILES.ligand_ff))
            tif.write('set default PBRadii mbondi2\n')
            # check if ligand is not protein and always load
            if self.FILES.ligand_mol2:
                tif.write('LIG = loadmol2 {}\n'.format(self.FILES.ligand_mol2))
                tif.write('check LIG\n')
                tif.write('loadamberparams {}\n'.format(self.ligand_frcmod))

            if not self.FILES.stability:
                tif.write('REC = loadpdb {}\n'.format(self.receptor_pdb_fixed))
                tif.write('saveamberparm REC {t} {p}REC.inpcrd\n'.format(t=self.receptor_pmrtop, p=self.FILES.prefix))
                if not self.FILES.ligand_mol2:
                    tif.write('LIG = loadpdb {}\n'.format(self.ligand_pdb_fixed))
                tif.write('saveamberparm LIG {t} {p}LIG.inpcrd\n'.format(t=self.ligand_pmrtop, p=self.FILES.prefix))

            tif.write('complex = loadpdb {}\n'.format(self.complex_pdb_fixed))
            tif.write('saveamberparm complex {t} {p}COM.inpcrd\n'.format(t=self.complex_pmrtop, p=self.FILES.prefix))
            tif.write('quit')

        tleap = self.external_progs['tleap'].full_path
        p = subprocess.Popen([tleap, '-f', '{}'.format(self.FILES.prefix + 'leap.in')], stdout=self.log,
                             stderr=self.log)
        if p.wait():
            raise MMPBSA_Error('%s failed when querying %s' % (tleap))

        if self.INPUT['alarun']:
            with open(self.FILES.prefix + 'mut_leap.in', 'w') as mtif:
                mtif.write('source {}\n'.format(ff_list[self.FILES.protein_ff]))
                mtif.write('source leaprc.DNA.bsc1\n')
                mtif.write('source leaprc.RNA.OL3\n')
                mtif.write('source leaprc.{}\n'.format(self.FILES.ligand_ff))
                mtif.write('set default PBRadii mbondi2\n')
                # check if ligand is not protein and always load
                if self.FILES.ligand_mol2:
                    mtif.write('LIG = loadmol2 {}\n'.format(self.FILES.ligand_mol2))
                    mtif.write('check LIG\n')
                    mtif.write('loadamberparams {}\n'.format(self.ligand_frcmod))

                if not self.FILES.stability:
                    if self.INPUT['mutant'].lower() in ['rec', 'receptor']:
                        mtif.write('mut_rec = loadpdb {}\n'.format(self.mutant_receptor_pdb_fixed))
                        mtif.write('saveamberparm mut_rec {t} {p}MUT_REC.inpcrd\n'.format(t=self.mutant_receptor_pmrtop,
                                                                                          p=self.FILES.prefix))
                        self.mutant_ligand_pmrtop = None
                    else:
                        mtif.write('mut_lig = loadpdb {}\n'.format(self.mutant_ligand_pdb_fixed))
                        self.mutant_receptor_pmrtop = self.receptor_pmrtop
                        mtif.write('saveamberparm mut_lig {t} {p}MUT_LIG.inpcrd\n'.format(t=self.mutant_ligand_pmrtop,
                                                                                          p=self.FILES.prefix))
                        self.mutant_receptor_pmrtop = None
                mtif.write('mut_com = loadpdb {}\n'.format(self.mutant_complex_pdb_fixed))
                mtif.write('saveamberparm mut_com {t} {p}MUT_COM.inpcrd\n'.format(t=self.mutant_complex_pmrtop,
                                                                                  p=self.FILES.prefix))
                mtif.write('quit')

            # p1 = subprocess.check_output('{t} -f {f}'.format(t=tleap, f=self.FILES.prefix + 'mut_leap.in'),
            #                              stderr=subprocess.STDOUT, shell=True)
            p1 = subprocess.Popen([tleap, '-f', '{}'.format(self.FILES.prefix + 'mut_leap.in')], stdout=self.log,
                                 stderr=self.log)
            if p1.wait():
                raise MMPBSA_Error('%s failed when querying %s' % (tleap))

        else:
            self.mutant_complex_pmrtop = None

        return (self.complex_pmrtop, self.receptor_pmrtop, self.ligand_pmrtop, self.mutant_complex_pmrtop,
                self.mutant_receptor_pmrtop, self.mutant_ligand_pmrtop)
