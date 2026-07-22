import halcon as ha

device = "3408e1d8dbbe_FlukeProcessInstruments_TV46L1260100039Hz"

acq = ha.open_framegrabber(
    "GigEVision2",
    0,0,0,0,0,0,
    "progressive",
    -1,
    "default",
    -1,
    "false",
    "default",
    device,
    0,
    -1
)


print("="*80)
print("AVAILABLE PARAMETERS")
print("="*80)

params = ha.get_framegrabber_param(
    acq,
    "available_param_names"
)

for p in params:
    try:
        value = ha.get_framegrabber_param(acq, p)
        print(f"{p:40} : {value}")
    except Exception:
        pass

ha.close_framegrabber(acq)