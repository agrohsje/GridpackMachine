import os
import fileinput
import logging
import shutil
import pathlib
import json
import time
from copy import deepcopy
from config import Config
from utils import get_git_branches
from user import User


CORES = 8
MEMORY = CORES * 2000


class Gridpack():

    def __init__(self, data):
        self.logger = logging.getLogger()
        self.data = data

    def validate(self):
        branches = get_git_branches(Config.get('gen_repository'), cache=True)
        genproductions = self.data['genproductions']
        if genproductions not in branches:
            return f'Bad GEN productions branch "{genproductions}"'

        beam = self.data['beam']
        if beam <= 0:
            return f'Bad beam "{beam}"'

        events = self.data['events']
        if events <= 0:
            return f'Bad events "{events}"'

        return None

    def reset(self):
        self.set_status('new')
        self.data['archive'] = ''
        self.set_condor_status('')
        self.set_condor_id(0)

    def get_id(self):
        return self.data['_id']

    def get_status(self):
        return self.data['status']

    def set_status(self, status):
        """
        Setter for status
        """
        self.data['status'] = status

    def get_condor_status(self):
        return self.data['condor_status']

    def set_condor_status(self, condor_status):
        """
        Setter for condor status
        """
        self.data['condor_status'] = condor_status

    def get_condor_id(self):
        return self.data['condor_id']

    def set_condor_id(self, condor_id):
        """
        Setter for condor id
        """
        self.data['condor_id'] = condor_id

    def get_json(self):
        return deepcopy(self.data)

    def get_dataset_dict(self):
        """
        Return a dictionary from cards directory
        """
        if hasattr(self, 'dataset_dict'):
            return self.dataset_dict

        generator = self.data['generator']
        process = self.data['process']
        dataset_name = self.data['dataset']
        files_dir = Config.get('gridpack_files_path')
        cards_path = os.path.join(files_dir, 'cards', generator, process, dataset_name)
        dataset_dict_file = os.path.join(cards_path, f'{dataset_name}.json')
        self.logger.debug('Reading %s', dataset_dict_file)
        with open(dataset_dict_file) as input_file:
            dataset_dict = json.load(input_file)

        self.dataset_dict = dataset_dict
        return dataset_dict

    def mkdir(self):
        """
        Make local directory of gridpack
        """
        gridpack_id = self.get_id()
        local_directory = f'gridpacks/{gridpack_id}'
        pathlib.Path(local_directory).mkdir(parents=True, exist_ok=True)

    def rmdir(self):
        """
        Remove local directory of gridpack
        """
        gridpack_id = self.get_id()
        local_directory = f'gridpacks/{gridpack_id}'
        shutil.rmtree(local_directory, ignore_errors=True)

    def local_dir(self):
        """
        Return path to local directory of gridpack files
        """
        gridpack_id = self.get_id()
        return os.path.abspath(f'gridpacks/{gridpack_id}')

    def add_history_entry(self, entry):
        """
        Add a simple string history entry
        """
        user = User().get_username()
        timestamp = int(time.time())
        entry = entry.strip()
        self.data.setdefault('history', []).append({'user': user,
                                                    'time': timestamp,
                                                    'action': entry})

    def get_users(self):
        """
        Return a list of unique usernames of users in history
        """
        users = set(x['user'] for x in self.data['history'] if x['user'] != 'automatic')
        return sorted(list(users))

    def prepare_default_card(self):
        """
        Copy default cards to local directory
        """
        generator = self.data['generator']
        process = self.data['process']
        dataset_name = self.data['dataset']
        files_dir = Config.get('gridpack_files_path')
        cards_path = os.path.join(files_dir, 'cards', generator, process, dataset_name) 
        local_cards_path = os.path.join(self.local_dir(), 'input_cards')
        pathlib.Path(local_cards_path).mkdir(parents=True, exist_ok=True)
        self.logger.debug('Copying %s/*.dat to %s', cards_path, local_cards_path)
        os.system(f'cp {cards_path}/*.dat {local_cards_path}')

    def prepare_run_card(self):
        """
        Copy cards from campaign template directory to local directory
        """
        campaign = self.data['campaign']
        generator = self.data['generator']
        dataset_name = self.data['dataset']
        files_dir = Config.get('gridpack_files_path')
        template_path = os.path.join(files_dir, 'Campaigns', campaign, generator, 'Templates')
        run_card_file_path = os.path.join(self.local_dir(), 'input_cards', f'{dataset_name}_run_card.dat')
        if dataset_name.rsplit("_", 1)[1].startswith("amcatnlo"):
            os.system(f"cp {template_path}/NLO_run_card.dat {run_card_file_path}")
        elif dataset_name.rsplit("_", 1)[1].startswith("madgraph"):
            os.system(f"cp {template_path}/LO_run_card.dat {run_card_file_path}")
        else:
            self.logger.error('Could not find "amcatnlo" or "madgraph" in "%s"', dataset_name)
            raise Exception()

        with open(run_card_file_path) as input_file:
            self.logger.debug('Reading %s...', run_card_file_path)
            run_card_file = input_file.read()

        dataset_dict = self.get_dataset_dict()
        beam = str(self.data['beam'])
        run_card_file = run_card_file.replace('$ebeam1', beam)
        run_card_file = run_card_file.replace('$ebeam2', beam)
        for key, value in dataset_dict.get('run_card', {}).items():
            key = f'${key}'
            self.logger.debug('Replacing "%s" with "%s" in %s', key, value, run_card_file_path)
            run_card_file = run_card_file.replace(key, value)

        with open(run_card_file_path, 'w') as output_file:
            self.logger.debug('Writing %s...', run_card_file_path)
            output_file.write(run_card_file)

    def prepare_customize_card(self):
        """
        Copy cards from "modelparams" directory and customize them
        """
        dataset_dict = self.get_dataset_dict()
        scheme_name = dataset_dict.get('scheme')
        if not scheme_name:
            return

        campaign = self.data['campaign']
        generator = self.data['generator']
        dataset_name = self.data['dataset']
        files_dir = Config.get('gridpack_files_path')
        scheme_file = os.path.join(files_dir, 'Campaigns', campaign, generator, 'ModelParams', scheme_name)
        customized_file = os.path.join(self.local_dir(), 'input_cards',  f'{dataset_name}_customizecards.dat')
        self.logger.debug('Reading scheme file %s', scheme_file)
        with open(scheme_file) as scheme_file:
            scheme = scheme_file.read()

        scheme = scheme.split('\n')
        scheme += ['', '# User settings']
        for user_line in dataset_dict.get('user', []):
            self.logger.debug('Appeding %s', user_line)
            scheme += [user_line]

        scheme = '\n'.join(scheme)
        self.logger.debug('Writing customized scheme file %s', customized_file)
        with open(customized_file, 'w') as scheme_file:
            scheme_file.write(scheme)
            
    def prepare_powheg_card(self):
        
        """
        Create Powheg cards from templates and user specific input
        """
        self.logger.debug('Start preparing powheg card')
        # create new powheg steering file 
        local_cards_path = os.path.join(self.local_dir(), 'input_cards')
        pathlib.Path(local_cards_path).mkdir(parents=True, exist_ok=True)
        powheg_steering_file= os.path.join(local_cards_path, 'powheg.input')
        powheg_steering = open(powheg_steering_file, 'wt')        
        # fill with content of process specific template and adjust settings like beam energy, ...
        dataset_dict = self.get_dataset_dict()
        powheg_process=dataset_dict["powheg_process"]
        files_path = Config.get('gridpack_files_path')
        campaign = self.data['campaign']
        generator = self.data['generator']
        process_template_file = os.path.join(files_path, 'Campaigns', campaign, generator, 'Templates')+'/'+powheg_process+'.input'
        if not os.path.exists(process_template_file):
            self.logger.error('Could not find process template %s', process_template_file)
        else:
            self.logger.debug('Start filling %s with process %s template %s', powheg_steering_file, powheg_process, process_template_file)
        beam = str(self.data['beam'])
        self.logger.debug('Going to use beamenergy of %s', beam)
        # agrohsje: still sync strategy for PDF and fix pdf input 
        pdf = "325300"
        self.logger.debug('Going to use LHAPDF %s', pdf)
        for line in fileinput.input(files = process_template_file):         
            line = line.replace('$ebeam1', beam)
            line = line.replace('$ebeam2', beam)
            line = line.replace('$pdf1', pdf)
            line = line.replace('$pdf2', pdf)
            powheg_steering.write(line)
        powheg_steering.close()
        
        # add campaign and user specific settings to powheg steering file 
        powheg_steering = open(powheg_steering_file, 'a')        
        # append campaign specific settings for process 

        modelparams_file = os.path.join(files_path, 'Campaigns', campaign, generator, 'ModelParams')+'/'+powheg_process+'.input'
        if not os.path.exists(modelparams_file):
            self.logger.error('Could not find model parameters %s for process %s', modelparams_file, powheg_process)
            raise Exception()
        self.logger.debug('Appeding content of %s to %s', modelparams_file, powheg_steering_file)
        modelparams = open(modelparams_file, 'r')
        powheg_steering.write(modelparams.read())
        # append user specific settings 
        if not 'powheg_card' in dataset_dict:
            self.logger.error('Could not find powheg_card block in dataset dictionary')
            raise Exception()
        for user_line in dataset_dict.get('powheg_card', []):
            self.logger.debug('Appeding %s', user_line)
            powheg_steering.write(user_line+'\n')
        powheg_steering.close()

    def prepare_procname_card(self):

        """
        Create card with just the process name for proper Powheg gridpack production 
        """
        self.logger.debug('Preparing card with Powheg process name')
        local_cards_path = os.path.join(self.local_dir(), 'input_cards')
        pathlib.Path(local_cards_path).mkdir(parents=True, exist_ok=True)
        powheg_process_name_file= os.path.join(local_cards_path, 'process.dat')
        powheg_process_name = open(powheg_process_name_file, 'wt')        
        dataset_dict = self.get_dataset_dict()
        if not 'powheg_process' in dataset_dict:
            self.logger.error('Could not find powheg_process block in dataset dictionary')
            raise Exception()
        powheg_process = dataset_dict.get('powheg_process')
        powheg_process_name.write(powheg_process+'\n')
        self.logger.debug('Add Powheg process name %s to %s', powheg_process, powheg_process_name_file)
        powheg_process_name.close()
        
    def prepare_card_archive(self):
        """
        Make an archive with all necessary card files
        """
        generator = self.data["generator"]
        if generator == "MadGraph5_aMCatNLO":
            self.prepare_default_card()
            self.prepare_run_card()
            self.prepare_customize_card()
        elif generator == "Powheg":
            self.prepare_powheg_card()
            self.prepare_procname_card()
        else:
            self.logger.error('Generator=%s unknown', generator)
            raise Exception()

        local_dir = self.local_dir()
        os.system(f"tar -czvf {local_dir}/input_cards.tar.gz -C {local_dir} input_cards")

    def prepare_script(self):
        """
        Make a bash script that will run in condor
        """
        repository = Config.get('gen_repository')
        generator = self.data['generator']
        dataset_name = self.data['dataset']
        genproductions = self.data['genproductions']
        command = ['#!/bin/sh',
                   'export HOME=$(pwd)',
                   'export ORG_PWD=$(pwd)',
                   f'export NB_CORE={CORES}',
                   f'wget https://github.com/{repository}/tarball/{genproductions} -O genproductions.tar.gz',
                   'tar -xzf genproductions.tar.gz',
                   f'GEN_FOLDER=$(ls -1 | grep {repository.replace("/", "-")}- | head -n 1)',
                   'echo $GEN_FOLDER',
                   'mv $GEN_FOLDER genproductions',
                   'cd genproductions',
                   'git init',
                   'cd ..',
                   f'mv input_cards.tar.gz genproductions/bin/{generator}/',
                   f'cd genproductions/bin/{generator}',
                   'tar -xzf input_cards.tar.gz',
                   'echo "Running gridpack_generation.sh"',
                   # Set "pdmv" queue
                   f'./gridpack_generation.sh {dataset_name} input_cards pdmv',
                   'echo "Archives after gridpack_generation.sh:"',
                   'ls -lha *.tar.xz',
                   f'mv {dataset_name}*.xz $ORG_PWD']

        script_name = f'GRIDPACK_{self.get_id()}.sh'
        script_path = os.path.join(self.local_dir(), script_name)
        self.logger.debug('Writing sh script to %s', script_path)
        with open(script_path, 'w') as script_file:
            script_file.write('\n'.join(command))

        os.system(f"chmod a+x {script_path}")

    def prepare_jds_file(self):
        """
        Make condor job description file
        """
        gridpack_id = self.get_id()
        script_name = f'GRIDPACK_{gridpack_id}.sh'
        jds = [f'executable              = {script_name}',
               'transfer_input_files    = input_cards.tar.gz',
               'when_to_transfer_output = on_exit',
               'should_transfer_files   = yes',
               '+JobFlavour             = "testmatch"',
               # '+JobFlavour             = "longlunch"',
               'output                  = output.log',
               'error                   = error.log',
               'log                     = job.log',
               f'RequestCpus             = {CORES}',
               f'RequestMemory           = {MEMORY}',
               '+accounting_group       = highprio',
               '+AccountingGroup        = "highprio.pdmvserv"',
               '+AcctGroup              = "highprio"',
               '+AcctGroupUser          = "pdmvserv"',
               '+DESIRED_Sites          = "T2_CH_CERN"',
               '+REQUIRED_OS            = "rhel7"',
               'leave_in_queue          = JobStatus == 4 && (CompletionDate =?= UNDEFINED || ((CurrentTime - CompletionDate) < 7200))',
               '+CMS_Type               = "test"',
               '+CMS_JobType            = "PdmVGridpack"',
               '+CMS_TaskType           = "PdmVGridpack"',
               '+CMS_SubmissionTool     = "Condor_SI"',
               '+CMS_WMTool             = "Condor_SI"',
               'queue']

        jds_name = f'GRIDPACK_{gridpack_id}.jds'
        jds_path = os.path.join(self.local_dir(), jds_name)
        self.logger.debug('Writing JDS to %s', jds_path)
        with open(jds_path, 'w') as jds_file:
            jds_file.write('\n'.join(jds))

    def __str__(self) -> str:
        gridpack_id = self.get_id()
        campaign = self.data['campaign']
        dataset = self.data['dataset']
        generator = self.data['generator']
        status = self.get_status()
        condor_status = self.get_condor_status()
        condor_id = self.get_condor_id()
        return (f'Gridpack <{gridpack_id}> campaign={campaign} dataset={dataset} '
                f'generator={generator} status={status} condor={condor_status} ({condor_id})')
