#!/usr/bin/env python

import sys
import os.path
import yaml
import logging
import time

# to be made into a package later
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'lib'))
import clud.aws.connections
import clud.aws.keypair
import clud.aws.secgroup
import clud.aws.instance
import clud.aws.ebs
import clud.aws.ami

import clud.ssh.pkgs
import clud.ssh.initramfs
import clud.ssh.fileops
import clud.ssh.dev
import clud.ssh.util
import clud.ssh.awstools

def get_config(yfile):
  required_keys = ['aws_region',
		    'keypair_name',
		    'keypair_dir',
		    'vpc_id',
		    'subnet_id',
		    'availability_zone',
		    'security_group_name',
		    'source_ami',
		    'target_ami_name',
		    'target_ami_desc',
		    'instance_type',
		    'my_public_ip',
		    'src_root_dev',
		    'tmp_vol_dev',
		    'username',
		    'hostname',
		    'pkgs']

  stream = open(yfile, 'r')
  yconf = yaml.load(stream)

  for reqkey in required_keys:

    if reqkey not in yconf.keys():
      logging.critical('required key %s not found in %s. exiting.' %
	(reqkey, yfile))
      sys.exit(-1)

  return yconf

def make_source_ec2(ec2_conn, yconfig):
  sg = clud.aws.secgroup.get_sg(ec2_conn, yconfig['security_group_name'])

  instance = clud.aws.instance.run(ec2_conn,
				    yconfig['keypair_name'],
				    yconfig['instance_type'],
				    sg.id,
				    yconfig['subnet_id'],
				    yconfig['source_ami'],
				    yconfig['hostname'])
  logging.info('launched instance: %s' % instance.id)
  return instance

def attach_new_root(ec2_conn, yconfig, size, instance):
  new_root_vol = clud.aws.ebs.create(ec2_conn, size, 
				    yconfig['availability_zone'])

  logging.info('attaching volume %s to %s' % (new_root_vol.id, instance.id))

  if not clud.aws.instance.attach_vol(ec2_conn, instance, new_root_vol, 
      yconfig['tmp_vol_dev']):
    logging.critical('failed to attach %s to %s. exiting' % (new_root_vol.id,
		    instance.id))
    sys.exit(-3)
  return new_root_vol

def copy_to_source_ec2(instance, yconfig, src_prefix, keypair_path):

  for filespec in yconfig['copy_files']:
    filespec['src_path'] = src_prefix + filespec['path']

    logging.info('copying %s to %s' % (filespec['path'], instance.ip_address))
    clud.ssh.fileops.copy(instance.ip_address, yconfig['username'],
			  keypair_path, filespec)

def swap_vols_ec2(ec2_conn, yconfig, new_root_vol, instance):
  root_dev = instance.root_device_name
  root_vol_id = clud.aws.instance.root_vol_id(ec2_conn, instance)
  root_vol = clud.aws.ebs.vol_from_id(ec2_conn, root_vol_id)

  if not clud.aws.instance.detach_vol(ec2_conn, instance, root_vol):
    logging.critical('failed to detach old root vol %s from %s' % 
		      (root_vol_id, instance.id))
    sys.exit(-6)

  if not clud.aws.ebs.delete(ec2_conn, root_vol):
    logging.critical('failed to delete old root vol %s' % root_vol_id)
    sys.exit(-6)

  if not clud.aws.instance.detach_vol(ec2_conn, instance, new_root_vol):
    logging.critical('failed to detach new root vol %s from %s' % 
		      (root_vol_id, instance.id))
    sys.exit(-6)

  block_dev_map = instance.block_device_mapping
  while block_dev_map != {}:
    time.sleep(10)
    instance.update()
    block_dev_map = instance.block_device_mapping

  if not clud.aws.instance.attach_vol(ec2_conn, instance, new_root_vol,
				       	root_dev):
    logging.critical('failed to attach new root vol %s to %s' % 
		      (root_vol_id, instance.id))
    sys.exit(-6)

def make_ami(ec2_conn, instance, yconfig):
  ami_name = yconfig['target_ami_name'] + '-' + time.strftime('%Y-%m-%d-%H-%M')
  ami_desc = yconfig['target_ami_desc']
  ami = clud.aws.ami.create_from_instance(ec2_conn, instance, ami_name,
					  ami_desc)
  return ami

def cleanup_ec2(ec2_conn, yconfig, instance, new_root_vol):
  clud.aws.instance.terminate(ec2_conn, instance.id)

  if not clud.aws.ebs.delete(ec2_conn, new_root_vol):
    logging.critical('failed to delete new root vol %s' % new_root_vol.id)
    sys.exit(-6)
  

def usage():
  print "no no no!"
  sys.exit(1)

def keypair_or_die(ec2_conn, keypair_name, keypair_dir):

  key = clud.aws.keypair.create_unless_exists(ec2_conn, keypair_name,
					      keypair_dir)
  if key is None:
    logging.critical('failed to create key. exiting')
    sys.exit(-2)

def main():
  if not len(sys.argv) == 2:
    usage()

  logging.basicConfig(level=logging.INFO)

  yconfig = get_config(sys.argv[1])

  ec2_conn = clud.aws.connections.ec2(yconfig['aws_region'])

  key = keypair_or_die(ec2_conn, 
			yconfig['keypair_name'], yconfig['keypair_dir'])
  keypair_path = os.path.join(yconfig['keypair_dir'], 
			      yconfig['keypair_name'] + '.pem')

  instance = make_source_ec2(ec2_conn, yconfig)

  logging.info('waiting for instance %s to boot' % instance.id)
  clud.ssh.util.wait_for_ssh(instance.ip_address, yconfig['username'],
			      keypair_path)

  new_root_vol_size = 8

  new_root_vol = attach_new_root(ec2_conn, yconfig, new_root_vol_size, instance)

  clud.ssh.pkgs.add(instance.ip_address, yconfig['username'], keypair_path, 
		    yconfig['pkgs'])

  clud.ssh.initramfs.rebuild(instance.ip_address, yconfig['username'], 
			      keypair_path)

  src_prefix = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'files')
  copy_to_source_ec2(instance, yconfig, src_prefix, keypair_path)

  clud.ssh.awstools.add(instance.ip_address, yconfig['username'], keypair_path)

  clud.ssh.dev.rawcopy(instance.ip_address, yconfig['username'], keypair_path, 
	  yconfig['src_root_dev'], yconfig['tmp_vol_dev'])

  if not clud.aws.instance.stop(ec2_conn, instance):
    logging.critical('failed to stop %s. exiting.' % instance.id)
    sys.exit(-5)

  swap_vols_ec2(ec2_conn, yconfig, new_root_vol, instance)

  ami = make_ami(ec2_conn, instance, yconfig)

  cleanup_ec2(ec2_conn, yconfig, instance, new_root_vol)

  print ami.id
  sys.exit(0)

if __name__ == '__main__':
  main()

  
