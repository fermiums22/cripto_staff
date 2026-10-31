"""B: fixed signed flow/depth/acceleration rule; depth loss is NOT proven cancellation."""


def rule(x):
    side=1 if x[13]>=0 else -1
    if side*x[7]>.3 and side*x[13]>.6 and side*x[8]>.05 and side*x[4]>0 and x[11]<0:
        return side,abs(x[13])+abs(x[8])
    return None


FEATURES=(4,7,8,9,10,11,12,13,14,15,16)


if __name__=='__main__':
    from research.compare import main
    main('B')
