#!/usr/bin/env python
#Copyright (C) 2009-2010 :
#    Gabes Jean, naparuba@gmail.com
#    Gerhard Lausser, Gerhard.Lausser@consol.de
#    Gregory Starck, g.starck@gmail.com
#    Hartmut Goebel, h.goebel@goebel-consult.de
#
#This file is part of Shinken.
#
#Shinken is free software: you can redistribute it and/or modify
#it under the terms of the GNU Affero General Public License as published by
#the Free Software Foundation, either version 3 of the License, or
#(at your option) any later version.
#
#Shinken is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU Affero General Public License for more details.
#
#You should have received a copy of the GNU Affero General Public License
#along with Shinken.  If not, see <http://www.gnu.org/licenses/>.

import sys
import os
import time
import traceback

from shinken.objects import Config
from shinken.daemon import Daemon
from shinken.log import logger
print sys.path
from shinken.webui.bottle import Bottle, run, static_file, view, route

# Debug
import shinken.webui.bottle as bottle
bottle.debug(True)

#Import bottle lib to make bottle happy
bottle_dir = os.path.abspath(os.path.dirname(bottle.__file__))
sys.path.insert(0, bottle_dir)
#sys.path.insert(0, '.')
print "Sys path", sys.path

bottle.TEMPLATE_PATH.append(os.path.join(bottle_dir, 'views'))
bottle.TEMPLATE_PATH.append(bottle_dir)
print "Get view path", bottle.TEMPLATE_PATH
#os.chdir(bottle_dir)
print "GO pwd?", os.getcwd()



# Route static files css files
@route('/static/:path#.+#')
def server_static(path):
    #print "Getting static files from", os.path.join(my_dir, 'htdocs'), path
    return static_file(path, root=os.path.join(bottle_dir, 'htdocs'))

# hello/bla will use the hello_template.tpl template
@route('/hello/:name')
@view('hello_template')
def hello(name='World'):
    return dict(name=name)


# Output json
@route('/bla')
def bla():
    return {1:2}



# Main WebUI Class
class Webui(Daemon):

    def __init__(self, config_files, is_daemon, do_replace, debug, debug_file):
        
        super(Webui, self).__init__('webui', config_files[0], is_daemon, do_replace, debug, debug_file)
        
        self.config_files = config_files

        # Use to know if we must still be alive or not
        self.must_run = True
        
        self.conf = Config()



    def load_config_file(self):
        print "Loading configuration"
        # REF: doc/shinken-conf-dispatching.png (1)
        buf = self.conf.read_config(self.config_files)
        raw_objects = self.conf.read_config_buf(buf)

        self.conf.create_objects_for_type(raw_objects, 'arbiter')
        self.conf.create_objects_for_type(raw_objects, 'module')
        
        self.conf.early_arbiter_linking()

        ### Resume standard operations ###
        self.conf.create_objects(raw_objects)
        
        # Maybe conf is already invalid
        if not self.conf.conf_is_correct:
            sys.exit("***> One or more problems was encountered while processing the config files...")

        # Change Nagios2 names to Nagios3 ones
        self.conf.old_properties_names_to_new()

        # Create Template links
        self.conf.linkify_templates()

        # All inheritances
        self.conf.apply_inheritance()

        # Explode between types
        self.conf.explode()

        # Create Name reversed list for searching list
        self.conf.create_reversed_list()

        # Cleaning Twins objects
        self.conf.remove_twins()

        # Implicit inheritance for services
        self.conf.apply_implicit_inheritance()

        # Fill default values
        self.conf.fill_default()
        
        # Remove templates from config
        self.conf.remove_templates()
        
        # Pythonize values
        self.conf.pythonize()

        # Linkify objects each others
        self.conf.linkify()

        # applying dependancies
        self.conf.apply_dependancies()

        # Hacking some global parameter inherited from Nagios to create
        # on the fly some Broker modules like for status.dat parameters
        # or nagios.log one if there are no already available
        self.conf.hack_old_nagios_parameters()

        # Exlode global conf parameters into Classes
        self.conf.explode_global_conf()

        # set ourown timezone and propagate it to other satellites
        self.conf.propagate_timezone_option()

        # Look for business rules, and create teh dep trees
        self.conf.create_business_rules()
        # And link them
        self.conf.create_business_rules_dependencies()
        
        # Correct conf?
        self.conf.is_correct()

        # The conf can be incorrect here if the cut into parts see errors like
        # a realm with hosts and not schedulers for it
        if not self.conf.conf_is_correct:
            self.conf.show_errors()
            sys.exit("Configuration is incorrect, sorry, I bail out")

        logger.log('Things look okay - No serious problems were detected during the pre-flight check')

        # Now clean objects of temporary/unecessary attributes for live work:
        self.conf.clean()

        # Ok, here we must check if we go on or not.
        # TODO : check OK or not
        self.pidfile = os.path.abspath(self.conf.webui_lock_file)
        self.idontcareaboutsecurity = self.conf.idontcareaboutsecurity
        self.user = self.conf.shinken_user
        self.group = self.conf.shinken_group
        
        self.workdir = os.path.abspath(os.path.dirname(self.pidfile))

        self.port = self.conf.webui_port
        self.host = self.conf.webui_host
        
        logger.log("Configuration Loaded")
        print ""


    # Main loop function
    def main(self):
        try:
            # Log will be broks
            for line in self.get_header():
                self.log.log(line)

            self.load_config_file()
            print "GO pwd?", os.getcwd()
            #self.do_daemon_init_and_start(use_pyro=False)

            ## And go for the main loop
            self.do_mainloop()
        except SystemExit, exp:
            # With a 2.4 interpreter the sys.exit() in load_config_file
            # ends up here and must be handled.
            sys.exit(exp.code)
        except Exception, exp:
            logger.log("CRITICAL ERROR : I got an non recovarable error. I must exit")
            logger.log("You can log a bug ticket at https://sourceforge.net/apps/trac/shinken/newticket for geting help")
            logger.log("Back trace of it: %s" % (traceback.format_exc()))
            raise


    def setup_new_conf(self):
        """ Setup a new conf received from a Master arbiter. """
        conf = self.new_conf
        self.new_conf = None
        self.cur_conf = conf
        self.conf = conf        
        for arb in self.conf.arbiterlinks:
            if (arb.address, arb.port) == (self.host, self.port):
                self.me = arb
                arb.is_me = lambda: True  # we now definitively know who we are, just keep it.
            else:
                arb.is_me = lambda: False # and we know who we are not, just keep it.


    def do_loop_turn(self):
        if self.must_run:
            # Main loop
            self.run()


    # Get 'objects' from external modules
    # It can be used for get external commands for example
    def get_objects_from_from_queues(self):
        for f in self.modules_manager.get_external_from_queues():
            #print "Groking from module instance %s" % f
            while True:
                try:
                    o = f.get(block=False)
                    self.add(o)
                except Empty:
                    break
                # Maybe the queue got problem
                # log it and quit it
                except (IOError, EOFError), exp:
                    logger.log("Warning : an external module queue got a problem '%s'" % str(exp))
                    break

    # We wait (block) for arbiter to send us something
    def wait_for_master_death(self):
        print "Waiting for master death"
        timeout = 1.0
        self.last_master_speack = time.time()
        
        while not self.interrupted:
            elapsed, _, tcdiff = self.handleRequests(timeout)
            # if there was a system Time Change (tcdiff) then we have to adapt last_master_speak:
            if self.new_conf:
                self.setup_new_conf()
            if tcdiff:
                self.last_master_speack += tcdiff
            if elapsed:
                self.last_master_speack = time.time()
                timeout -= elapsed
                if timeout > 0:
                    continue
            
            timeout = 1.0            
            sys.stdout.write(".")
            sys.stdout.flush()

            # Now check if master is dead or not
            now = time.time()
            if now - self.last_master_speack > 5:
                print "Master is dead!!!"
                self.must_run = True
                break





    # Main function
    def run(self):
        # Now is fun : get all the fun running :)
        my_dir = os.path.abspath(os.path.dirname(__file__))

        # Got in my own dir, and add my path in sys.path
        os.chdir(bottle_dir)
        #os.chdir(my_dir)
        sys.path.append(my_dir)

        # Check if the view dir really exist
        if not os.path.exists(bottle.TEMPLATE_PATH[0]):
            logger.log('ERROR : the view path do not exist at %s' % bottle.TEMPLATE_PATH)
            sys.exit(2)



        from shinken.webui import impacts
        from shinken.webui import hostdetail

        print "Starting application"
        run(host=self.host, port=self.port)



        # Now we can get all initial broks for our satellites
        self.get_initial_broks_from_satellitelinks()

        suppl_socks = None

        # Now create the external commander. It's just here to dispatch
        # the commands to schedulers
        e = ExternalCommandManager(self.conf, 'dispatcher')
        e.load_arbiter(self)
        self.external_command = e

        print "Run baby, run..."
        timeout = 1.0             
        
        while self.must_run and not self.interrupted:
            
            elapsed, ins, _ = self.handleRequests(timeout, suppl_socks)
            
            # If FIFO, read external command
            if ins:
                now = time.time()
                ext_cmds = self.external_command.get()
                if ext_cmds:
                    for ext_cmd in ext_cmds:
                        self.external_commands.append(ext_cmd)
                else:
                    self.fifo = self.external_command.open()
                    if self.fifo is not None:
                        suppl_socks = [ self.fifo ]
                    else:
                        suppl_socks = None
                elapsed += time.time() - now

            if elapsed or ins:
                timeout -= elapsed
                if timeout > 0: # only continue if we are not over timeout
                    continue  
            
            # Timeout
            timeout = 1.0 # reset the timeout value

            # Try to see if one of my module is dead, and
            # try to restart previously dead modules :)
            self.check_and_del_zombie_modules()
            
            # Call modules that manage a starting tick pass
            self.hook_point('tick')
            
            self.dispatcher.check_alive()
            self.dispatcher.check_dispatch()
            # REF: doc/shinken-conf-dispatching.png (3)
            self.dispatcher.dispatch()
            self.dispatcher.check_bad_dispatch()

            # Now get things from our module instances
            self.get_objects_from_from_queues()

            # Maybe our satellites links raise new broks. Must reap them
            self.get_broks_from_satellitelinks()

            # One broker is responsible for our broks,
            # we must give him our broks
            self.push_broks_to_broker()
            self.get_external_commands_from_brokers()
            self.get_external_commands_from_receivers()
            # send_conf_to_schedulers()
            
            if self.nb_broks_send != 0:
                print "Nb Broks send:", self.nb_broks_send
            self.nb_broks_send = 0

            # Now send all external commands to schedulers
            for ext_cmd in self.external_commands:
                self.external_command.resolve_command(ext_cmd)
            # It's send, do not keep them
            # TODO: check if really send. Queue by scheduler?
            self.external_commands = []

            # If ask me to dump my memory, I do it
            if self.need_dump_memory:
                self.dump_memory()
                self.need_dump_memory = False


    def get_daemons(self, daemon_type):
        """ Returns the daemons list defined in our conf for the given type """
        # We get the list of the daemons from their links
        # 'schedulerlinks' for schedulers, 'arbiterlinks' for arbiters
        # and 'pollers', 'brokers', 'reactionners' for the others
        if (daemon_type == 'scheduler' or daemon_type == 'arbiter'):
            daemon_links = daemon_type+'links'
        else:
            daemon_links = daemon_type+'s'

        # shouldn't the 'daemon_links' (whetever it is above) be always present ?
        return getattr(self.conf, daemon_links, None)

    # Helper functions for retention modules
    # So we give our broks and external commands
    def get_retention_data(self):
        r = {}
        r['broks'] = self.broks
        r['external_commands'] = self.external_commands
        return r

    # Get back our data from a retention module
    def restore_retention_data(self, data):
        broks = data['broks']
        external_commands = data['external_commands']
        self.broks.update(broks)
        self.external_commands.extend(external_commands)
