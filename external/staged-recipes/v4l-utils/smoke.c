/* Link and call into libv4l2 to prove the package is usable, without needing a
 * capture device: v4l2_open on a nonexistent path must fail cleanly rather than
 * crash, which exercises load, init and the wrapper entry points. */
#include <libv4l2.h>
#include <stdio.h>

int main(void)
{
    int fd = v4l2_open("/nonexistent-v4l-device", 0);
    if (fd >= 0) {
        v4l2_close(fd);
        puts("unexpectedly opened a nonexistent device");
        return 1;
    }
    puts("libv4l2 linked and callable");
    return 0;
}
