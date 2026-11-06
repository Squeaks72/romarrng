/* romarr-plugin-launch: run one command as the unprivileged plugin user.
 *
 * Installed setuid root, mode 4750, group = ROMarr's own PGID (set by the
 * entrypoint), so only ROMarr's user can execute it; the plugin user cannot
 * use it to climb back. Without Landlock (Unraid's kernel has none) this is
 * what keeps a Hub plugin away from /config/romarr.json, whose mode is 0600
 * and owned by ROMarr's user.
 *
 * It switches to a fixed uid/gid, clears every supplementary group, sets
 * no_new_privs, proves it cannot become root again, then execs argv[1..].
 * It never reads the environment or accepts a uid argument.
 */
#define _GNU_SOURCE
#include <grp.h>
#include <stdio.h>
#include <sys/prctl.h>
#include <unistd.h>

#ifndef PLUGIN_UID
#define PLUGIN_UID 10001
#endif
#ifndef PLUGIN_GID
#define PLUGIN_GID 10001
#endif

int main(int argc, char **argv)
{
    if (argc < 2)
        return 64;
    if (geteuid() != 0 || getuid() == 0 || getuid() == PLUGIN_UID) {
        fprintf(stderr, "romarr-plugin-launch: must be run by ROMarr's user\n");
        return 77;
    }
    if (setgroups(0, NULL) != 0 ||
        setresgid(PLUGIN_GID, PLUGIN_GID, PLUGIN_GID) != 0 ||
        setresuid(PLUGIN_UID, PLUGIN_UID, PLUGIN_UID) != 0) {
        perror("romarr-plugin-launch: drop");
        return 71;
    }
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0) {
        perror("romarr-plugin-launch: no_new_privs");
        return 71;
    }
    if (setuid(0) == 0 || geteuid() == 0 || getgid() != PLUGIN_GID) {
        fprintf(stderr, "romarr-plugin-launch: privilege drop did not hold\n");
        return 70;
    }
    execv(argv[1], argv + 1);
    perror("romarr-plugin-launch: exec");
    return 127;
}
