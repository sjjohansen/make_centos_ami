#!/usr/bin/env python

import sys
import os.path
import yaml
import logging

# to be made into a package later
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'lib'))
import clud.aws.connections
import clud.aws.keypair
import clud.aws.secgroup
import clud.aws.instance
import clud.aws.ebs
import clud.ssh.pkgs

def get_config(yfile):
  required_keys = ['aws_region',
		    'keypair_name',
		    'keypair_dir',
		    'vpc_id',
		    'subnet_id',
		    'availability_zone',
		    'security_group_name',
		    'source_ami',
		    'instance_type',
		    'my_public_ip',
		    'tmp_vol_dev',
		    'username',
		    'pkgs']

  stream = open(yfile, 'r')
  yconf = yaml.load(stream)

  for reqkey in required_keys:

    if reqkey not in yconf.keys():
      logging.critical('required key %s not found in %s. exiting.' %
	(reqkey, yfile))
      sys.exit(-1)

  return yconf

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

  #logging.basicConfig(level=logging.DEBUG)

  yconfig = get_config(sys.argv[1])

  ec2_conn = clud.aws.connections.ec2(yconfig['aws_region'])
  key = keypair_or_die(ec2_conn, 
			yconfig['keypair_name'], yconfig['keypair_dir'])

  sg = clud.aws.secgroup.get_sg(ec2_conn, yconfig['security_group_name'])
  print sg.id

  vol = clud.aws.ebs.vol_from_id(ec2_conn, 'vol-3ccd522e')
  print vol

  instance = clud.aws.instance.instance_from_id(ec2_conn, 'i-297be9df')
  print instance
  print clud.aws.instance.public_ip(ec2_conn, instance)
  print clud.aws.instance.root_vol_id(ec2_conn, instance)

  #new_root_vol = clud.aws.ebs.create(ec2_conn, 8, yconfig['availability_zone'])
  new_root_vol = clud.aws.ebs.vol_from_id(ec2_conn, 'vol-ebc659f9')
  print new_root_vol

  if not clud.aws.instance.attach_vol(ec2_conn, instance, new_root_vol, 
      yconfig['tmp_vol_dev']):
    logging.critical('failed to attach %s to %s. exiting' % (new_root_vol.id,
		    instance.id))

  #if not clud.aws.instance.detach_vol(ec2_conn, instance, new_root_vol):
  #  logging.critical('failed to detach %s from %s. exiting' % (new_root_vol.id,
#		    instance.id))

  print instance.ip_address
  clud.ssh.pkgs.add(instance.ip_address, yconfig['username'], 
    os.path.join(yconfig['keypair_dir'], yconfig['keypair_name'] + '.pem'),
    yconfig['pkgs'])

  
  sys.exit(0)

if __name__ == '__main__':
  main()

