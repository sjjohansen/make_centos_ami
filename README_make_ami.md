Set an environment variable to do this in CBIG's AWS:
```bash
export AWS_DEFAULT_PROFILE=cbig
```
Create a keypair:
```bash
mkdir -p ~/pems/
aws ec2 create-key-pair --key-name sjkp --query 'KeyMaterial' --output text > ~/pems/sjkp.pem
chmod 0400 ~/pems/sjkp.pem
```
Use this script to work out your current IP:
```bash
curl -s -L 'https://www.google.com/search?q=whats+my+ip&ie=utf-8&oe=utf-8' \
| grep 'Client IP address' \
| sed -e 's/.*Client IP address: //' -e 's/).*//'
MYPUBLIC_IP=114.121.131.110
```
Create a security group (this is the default CBIG VPC)
```bash
aws ec2 create-security-group \
 --group-name sshonly-sjhome \
 --description "Allow SSH from remote IP as on `date '+%Y-%m-%d'`" \
 --vpc-id vpc-a04b42c2
SGID=sg-44b99d21

aws ec2 authorize-security-group-ingress \
--group-id $SGID \
--protocol tcp --port 22 --cidr "${MYPUBLIC_IP}/32"

```
Create a config file (in this case I'm using `conf/centos-au.yaml`)
Run build script:
```bash
source ~/pyenvs/aws/bin/activate

SUBNETID=subnet-12ffd766
SRC_AMI=ami-b3523089
aws ec2 run-instances --image-id $SRC_AMI \
--count=1 --instance-type t2.micro \
--key-name sjkp \
--security-group-ids $SGID --subnet-id $SUBNETID

INSTANCEID=i-34bbe7ea

aws ec2 describe-instances --instance-ids $INSTANCEID | egrep 'PublicIpAddress|AvailabilityZone|VolumeId'

PUBLICIP=52.64.214.131
AZ=ap-southeast-2a
OLD_ROOT_VOL=vol-fa41d93e

ssh -i ~/pems/sjkp.pem -oStrictHostKeyChecking=no root@$PUBLICIP hostname

ssh -i ~/pems/sjkp.pem root@$PUBLICIP "yum -y install epel-release cloud-init redhat-lsb cloud-utils-growpart  dracut-modules-growroot"
ssh -i ~/pems/sjkp.pem root@$PUBLICIP "yum -y install cloud-utils-growpart  dracut-modules-growroot"
ssh -i ~/pems/sjkp.pem root@$PUBLICIP "yum -y update"


scp -i ~/pems/sjkp.pem files/etc/selinux/config root@$PUBLICIP:/etc/selinux
ssh -i ~/pems/sjkp.pem root@$PUBLICIP 'chmod 0640 /etc/selinux/config; chown root:root /etc/selinux/config'

scp -i ~/pems/sjkp.pem files/etc/cloud/cloud.cfg root@$PUBLICIP:/etc/cloud
ssh -i ~/pems/sjkp.pem root@$PUBLICIP 'chmod 0664 /etc/cloud/cloud.cfg; chown root:root /etc/cloud/cloud.cfg'

ssh -i ~/pems/sjkp.pem root@$PUBLICIP 'cp /boot/initramfs-$(uname -r).img /boot/initramfs-$(uname -r).img.bak'
ssh -i ~/pems/sjkp.pem root@$PUBLICIP 'dracut -f'

aws ec2 create-volume --size 8 --availability-zone $AZ
NEW_ROOT_VOL=vol-d945dd1d

aws ec2 attach-volume --volume-id $NEW_ROOT_VOL --instance-id $INSTANCEID --device /dev/xvdz

ssh -i ~/pems/sjkp.pem root@$PUBLICIP "sfdisk -d /dev/xvda | sfdisk --force /dev/xvdz"
# kick off dd next
ssh -i ~/pems/sjkp.pem root@$PUBLICIP "dd bs=65536 if=/dev/xvda of=/dev/xvdz;sync"

aws ec2 stop-instances --instance-ids $INSTANCEID

aws ec2 detach-volume --volume-id $OLD_ROOT_VOL
aws ec2 detach-volume --volume-id $NEW_ROOT_VOL
aws ec2 attach-volume --volume-id $NEW_ROOT_VOL --instance-id $INSTANCEID --device /dev/sda1

aws ec2 create-image --instance-id $INSTANCEID \
--name "CBIG-CentOS-6.5-x86_64-base-`date '+%Y-%m-%d-%H%M'`" \
--description "CBIG base CentOS 6.5 x86_64 image created from official CentOS release"
NEW_AMI_ID=ami-42c99721

aws ec2 describe-images --image-ids $NEW_AMI_ID
aws ec2 create-tags --resources $NEW_AMI_ID --tags 'Key=Name,Value=CBIG-CentOS-6.5'

aws ec2 terminate-instances --instance-ids $INSTANCEID
aws ec2 delete-volume --volume-id $OLD_ROOT_VOL

aws ec2 run-instances \
--image-id $NEW_AMI_ID \
--count=1 --instance-type t2.micro \
--key-name sjkp \
--security-group-ids $SGID \
--subnet-id $SUBNETID \
--block-device-mapping '[ { "DeviceName": "/dev/sda1", "Ebs": { "DeleteOnTermination": true, "VolumeSize": 20 } } ]'
