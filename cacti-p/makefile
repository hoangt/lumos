TARGET = cacti

.PHONY: dbg opt depend clean clean_dbg clean_opt

all: lumos_install

lumos_install: opt
	/bin/cp obj_opt/_cacti.so ../lumos/model/mem
	/bin/cp cacti.py ../lumos/model/mem

dbg: $(TARGET).mk obj_dbg
	@$(MAKE) TAG=dbg -C . -f $(TARGET).mk

opt: $(TARGET).mk obj_opt
	@$(MAKE) TAG=opt -C . -f $(TARGET).mk

obj_dbg:
	mkdir $@

obj_opt:
	mkdir $@

clean: clean_dbg clean_opt lumos_clean

clean_dbg:
	@$(MAKE) TAG=dbg -C . -f $(TARGET).mk clean
	rm -rf obj_dbg

clean_opt:
	@$(MAKE) TAG=opt -C . -f $(TARGET).mk clean
	rm -rf obj_opt

lumos_clean:
	/bin/rm -f ../lumos/model/mem/_cacti.so ../lumos/model/mem/cacti.py
