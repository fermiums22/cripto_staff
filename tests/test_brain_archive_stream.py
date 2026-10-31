import gzip
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from brain_archive_stream import ArchiveSource,merged

DAY='2026-10-01';START=1790812800000


class ArchiveTests(unittest.TestCase):
    def book_file(self,path,stamps):
        with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
            records=[dict(topic='orderbook.200.SOLUSDT',type='snapshot' if i==0 else 'delta',ts=t,
                          data=dict(s='SOLUSDT',b=[['100','1']],a=[['101','1']],u=i+1,seq=i+1))
                     for i,t in enumerate(stamps)]
            z.writestr('fixture.data',''.join(json.dumps(r)+'\n' for r in records))

    def test_receipts_are_simulated_and_no_backward_arrival(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'book.zip';self.book_file(path,[START+1000,START+900,START+1200])
            source=ArchiveSource(path,'SOLUSDT',DAY,'book',250);rows=list(source)
            self.assertEqual([r['received_ms'] for r in rows],[START+1250,START+1250,START+1450])
            self.assertEqual(rows[1]['message']['ts'],START+900)
            self.assertEqual(source.stats['time_regressions'],1)
            self.assertTrue(source.stats['crc_complete'])
            self.assertTrue(all(r['receipt_source'].startswith('simulated') for r in rows))

    def test_exact_decimal_trade_time_and_rpi_exclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'trade.gz'
            with gzip.open(path,'wt') as f:
                f.write('timestamp,symbol,side,size,price,RPI\n')
                f.write('1790812800.1921,SOLUSDT,Buy,2,100,0\n')
                f.write('1790812800.2000,SOLUSDT,Sell,2,100,1\n')
            source=ArchiveSource(path,'SOLUSDT',DAY,'trades',350);rows=list(source)
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['received_ms'],START+542)
            self.assertEqual(rows[0]['message']['data'][0]['T'],START+192)
            self.assertEqual(source.stats['rpi_filtered'],1);self.assertTrue(source.stats['crc_complete'])

    def test_merge_is_chronological_without_future_source_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=Path(tmp)/'a.zip';b=Path(tmp)/'b.zip'
            self.book_file(a,[START+1000,START+2000]);self.book_file(b,[START+1100,START+1900])
            sources=[ArchiveSource(a,'SOLUSDT',DAY,'book',250),ArchiveSource(b,'SOLUSDT',DAY,'book',400)]
            rows=list(merged(sources))
            self.assertEqual([r['received_ms'] for r in rows],[START+1250,START+1500,START+2250,START+2300])

    def test_wrong_day_rejected_and_crc_not_claimed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'book.zip';self.book_file(path,[START-60001])
            source=ArchiveSource(path,'SOLUSDT',DAY,'book',250)
            with self.assertRaises(ValueError):list(source)
            self.assertFalse(source.stats['crc_complete'])

    def test_adjacent_day_overlap_is_excluded_without_skipping_crc(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'book.zip';self.book_file(path,[START+1000,START+86400000+1886])
            source=ArchiveSource(path,'SOLUSDT',DAY,'book',250);rows=list(source)
            self.assertEqual(len(rows),1)
            self.assertEqual(source.stats['boundary_records_excluded'],1)
            self.assertTrue(source.stats['crc_complete'])

    def test_truncated_gzip_cannot_publish_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'trade.gz'
            path.write_bytes(gzip.compress(b'timestamp,symbol,side,size,price,RPI\n1790812800.2,SOLUSDT,Buy,2,100,0\n')[:-5])
            source=ArchiveSource(path,'SOLUSDT',DAY,'trades',350)
            with self.assertRaises((EOFError,OSError)):list(source)
            self.assertFalse(source.stats['crc_complete'])


if __name__=='__main__':unittest.main()
