#!/usr/bin/perl
#
# quick and dirty script to reboot shairport if it has been idle for a while after being used.
# 
# Edit for the directory asound makes when it is playing /proc/asound/(this will be unique to you)/...
# Edit for the backlight path /sys/class/backlight/(this will be unique to you)/brightness or change to /dev/null if you don't want backlight settings
#
# add to /etc/rc.local
#   nohup perl /path/to/activity.pl >/dev/null 2>&1 &
# and it will run forever.
# 10 minutes after /proc/asound/... is either gone or says closed, shairport will be restarted using service restart..
# 

my $brite = 1;

#
# Change these two for your set up.
#
my $USB = "/proc/asound/C20/pcm0p/sub0/hw_params";
my $BKLIGHT = "/sys/class/backlight/10-0045/brightness";

while(1) {
	my $off = 0;
	if (-e $USB) {
		open(P, "<$USB");
		while(<P>) {
			if (/closed/) {
				$off = 1;
			}
		}
		close(P);
  	} else {
		$off = 1;
	}

	$idle_ct++ if ($off);
	$idle_ct = 0 if (!$off);

	if (!$idle_ct && $brite != 200) {
		open(B, ">$BKLIGHT");
		print B "200\n";
		close(B);
		$brite = 200;
	}
	if ($idle_ct == 10 && $brite != 0) {
		open(B, ">$BKLIGHT");
		print B "0\n";
		close(B);
		$brite = 0;
	}
	#
	if (rand() > 0.98) {
		open(B, ">$BKLIGHT);
		print B "$brite\n";
		close(B);
	}
	`service shairport-sync restart` if ($idle_ct == 600);
	sleep(1);
}

exit(0);
